"""Headless orchestration loop (spec §7).

Each tick: simulator.tick -> detector.detect (+ active injected events) ->
decision_engine.decide -> approval gate -> dispatcher.apply -> audit log.
The same `state` + components are reused by the Streamlit UI in M7."""

from typing import Callable

from fleet.contracts.state import WorldState, ApprovalStatus, EventType
from fleet.factory import Components
from fleet.dispatch.approval import should_auto_approve
from fleet.dispatch.dispatcher import RESOLVE_ACTIONS
from fleet.routing.planner import (
    plan_routes, reroute, plan_total_minutes, preview_reroute_affected,
)


def _reconcile_detected(state: WorldState, detected) -> None:
    """Give detector output a lifecycle in state.events so a standing condition
    (e.g. a permanently flooded edge) is a single persistent event, not a fresh
    one every tick. Detector events use deterministic ids, so:
      - a detected id not already active is appended (it just started);
      - a previously-detected (DET_*) event no longer present is closed.
    Injected/simulator events are left untouched."""
    active = {e.id: e for e in state.get_active_events()}
    detected_ids = {e.id for e in detected}
    for e in detected:
        if e.id not in active:
            state.events.append(e)
    for eid, e in active.items():
        if eid.startswith("DET_") and eid not in detected_ids:
            e.ended_at = state.clock


def is_event_on_any_route(state: WorldState, event) -> bool:
    if event.target in state.customers or event.target == "DEPOT":
        for route in state.plan.values():
            unvisited = [s.customer_id for s in route.stops if s.actual_arrival is None]
            if event.target in unvisited:
                return True
        return False
    elif "->" in event.target:
        a, b = event.target.split("->", 1)
        if "#" in b:
            b = b.split("#")[0]
        import networkx as nx
        for vid, route in state.plan.items():
            if not route.stops: continue
            v = state.get_vehicle(vid)
            from fleet.contracts.state import VehicleStatus
            if v and v.status == VehicleStatus.AT_DEPOT and not [s for s in route.stops if s.actual_arrival is None]:
                continue

            # Use base_time_minutes only for the event target edge (simulate
            # "what if this disruption weren't here?") but keep effective_time for
            # all other edges so existing conditions still shape the route.
            G = nx.DiGraph()
            for e in state.road_graph.edges.values():
                is_target = (e.id == event.target) or (e.id.startswith(event.target + "#"))
                weight = e.base_time_minutes if is_target else e.effective_time
                if G.has_edge(e.from_node, e.to_node):
                    G[e.from_node][e.to_node]['weight'] = min(G[e.from_node][e.to_node]['weight'], weight)
                else:
                    G.add_edge(e.from_node, e.to_node, weight=weight)
            
            visited = [s for s in route.stops if s.actual_arrival is not None]
            unvisited = [s for s in route.stops if s.actual_arrival is None]
            current_node = visited[-1].customer_id if visited else "DEPOT"
            
            # The future path is from current_node -> unvisited_1 -> ... -> DEPOT
            nodes = [current_node] + [s.customer_id for s in unvisited] + ["DEPOT"]
            
            for i in range(len(nodes) - 1):
                u, v_node = nodes[i], nodes[i+1]
                if u not in G or v_node not in G: continue
                if u == v_node: continue
                try:
                    path = nx.shortest_path(G, source=u, target=v_node, weight="weight")
                    for j in range(len(path) - 1):
                        if path[j] == a and path[j+1] == b:
                            return True
                except nx.NetworkXNoPath:
                    continue
        return False
    return True


def get_affected_vehicle_ids(state: WorldState, event) -> list:
    """Return IDs of vehicles whose current planned route passes through the
    event area (edge or node).  Uses the same base-time trick as
    is_event_on_any_route: check whether the vehicle would naturally use the
    event target without the disruption penalty."""
    affected = []
    for vid, route in state.plan.items():
        if not route or not route.stops:
            continue
        unvisited = [s for s in route.stops if s.actual_arrival is None]
        if not unvisited:
            continue
        visited = [s for s in route.stops if s.actual_arrival is not None]
        current_node = visited[-1].customer_id if visited else "DEPOT"

        if event.target in state.customers:
            if any(s.customer_id == event.target for s in unvisited):
                affected.append(vid)
            continue

        if "->" not in event.target:
            continue

        a, b = event.target.split("->", 1)
        if "#" in b:
            b = b.split("#")[0]

        import networkx as nx
        G = nx.DiGraph()
        for e in state.road_graph.edges.values():
            is_target = (e.id == event.target) or (e.id.startswith(event.target + "#"))
            weight = e.base_time_minutes if is_target else e.effective_time
            if G.has_edge(e.from_node, e.to_node):
                G[e.from_node][e.to_node]["weight"] = min(
                    G[e.from_node][e.to_node]["weight"], weight)
            else:
                G.add_edge(e.from_node, e.to_node, weight=weight)

        nodes = [current_node] + [s.customer_id for s in unvisited] + ["DEPOT"]
        found = False
        for i in range(len(nodes) - 1):
            u, v_node = nodes[i], nodes[i + 1]
            if u not in G or v_node not in G or u == v_node:
                continue
            try:
                path = nx.shortest_path(G, source=u, target=v_node, weight="weight")
                for j in range(len(path) - 1):
                    if path[j] == a and path[j + 1] == b:
                        found = True
                        break
            except nx.NetworkXNoPath:
                pass
            if found:
                break
        if found:
            affected.append(vid)

    return affected


def run_loop(state: WorldState, components: Components, n_ticks: int,
             settings, logger: Callable[..., None] = print) -> WorldState:
    if not state.plan and state.total_orders_pending() > 0:
        plan_routes(state, components.optimizer)
    for _ in range(n_ticks):
        components.simulator.tick(state)

        _reconcile_detected(state, components.detector.detect(state))

        # Decide once per event: skip any active event that already has a decision.
        # This bounds state.decisions and stops a standing condition re-firing
        # (and re-wiping the plan) every tick.
        handled = {d.event_id for d in state.decisions}
        # Build the set of edge targets already handled so we can skip the reverse
        # direction of a bidirectional flood/jam (both directed edges map to the same
        # physical road; routing around one already routes around the other).
        handled_targets = {
            e.target for e in state.events if e.id in handled
        }
        events = []
        for e in state.get_active_events():
            if e.id in handled:
                continue
            # Skip reverse edge if the forward direction is already being handled.
            if "->" in e.target:
                raw_b = e.target.split("->", 1)[1]
                b = raw_b.split("#")[0]
                a = e.target.split("->", 1)[0]
                if f"{b}->{a}" in handled_targets:
                    continue
            if not is_event_on_any_route(state, e):
                continue
            events.append(e)

        severity_by_event = {e.id: e.severity for e in events}
        decisions = components.decision_engine.decide(state, events)

        needs_resolve = False
        resolve_decisions = []
        for d in decisions:
            state.decisions.append(d)
            severity = severity_by_event.get(d.event_id)
            from fleet.contracts.state import DecisionAction
            
            if d.action not in (DecisionAction.REROUTE, DecisionAction.RESCHEDULE) and should_auto_approve(d, severity, settings):
                d.approval_status = ApprovalStatus.APPROVED
                d.approved_by = "auto"
                d.approved_at = state.clock
                components.dispatcher.apply(state, d)
                if d.action in RESOLVE_ACTIONS:
                    needs_resolve = True
                    resolve_decisions.append(d)
                verdict = "AUTO-APPLIED"
            else:
                verdict = "QUEUED(approval)"
                from fleet.contracts.state import DecisionAction
                if d.action in (DecisionAction.REROUTE, DecisionAction.RESCHEDULE):
                    try:
                        # Find only the vehicles whose route is affected by this event.
                        ev = next((e for e in state.events if e.id == d.event_id), None)
                        if ev is not None:
                            affected_vids = get_affected_vehicle_ids(state, ev)
                        else:
                            affected_vids = list(state.plan.keys())

                        _, proposed = preview_reroute_affected(
                            state, components.optimizer, affected_vids)

                        # Node-sequence map for UI display (green dashed paths).
                        # Show the rerouted path from the vehicle's current
                        # position → new proposed stops → DEPOT.
                        routes = {}
                        for vid, vr in proposed.items():
                            visited_s = [s for s in vr.stops if s.actual_arrival is not None]
                            unvisited_s = sorted(
                                [s for s in vr.stops if s.actual_arrival is None],
                                key=lambda s: s.sequence)
                            cur = visited_s[-1].customer_id if visited_s else "DEPOT"
                            routes[vid] = (
                                [cur]
                                + [s.customer_id for s in unvisited_s]
                                + ["DEPOT"]
                            )
                        if d.execution_result is None:
                            d.execution_result = {}
                        d.execution_result["proposed_routes"] = routes

                        # Store the full VehicleRoute objects so approve() can apply
                        # the pre-computed plan without re-solving from scratch.
                        d.impact_estimate["_proposed_plan"] = proposed
                    except Exception as e:
                        print(f"Failed to compute preview plan: {e}")
            logger(f"t={state.sim_tick} clock={state.clock} "
                   f"{d.action.value} <- {d.event_id} [{verdict}]")

        if needs_resolve and state.total_orders_pending() > 0:
            before = plan_total_minutes(state)
            reroute(state, components.optimizer)
            added = max(0.0, plan_total_minutes(state) - before)
            # Record the *measured* delay the re-solve caused, replacing the
            # engine's self-estimate so the UI reflects reality.
            for d in resolve_decisions:
                d.impact_estimate["added_delay_min"] = round(added, 1)

        logger(f"t={state.sim_tick} clock={state.clock} "
               f"active_events={len(state.get_active_events())} "
               f"pending={len(state.get_pending_decisions())}")
    return state


def main() -> None:
    from fleet.scenarios import build_sample_state
    from fleet.factory import build_components
    from config.settings import load_settings
    from fleet.contracts.state import EventType, EventSeverity

    settings = load_settings()
    state = build_sample_state()
    components = build_components(settings)
    # demo: inject one traffic event so the decision path is visible
    components.simulator.inject_event(state, EventType.TRAFFIC, "DEPOT->C001",
                                      EventSeverity.LOW)
    run_loop(state, components, n_ticks=10, settings=settings)


if __name__ == "__main__":
    main()
