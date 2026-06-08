"""Headless orchestration loop (spec §7).

Each tick: simulator.tick -> detector.detect (+ active injected events) ->
decision_engine.decide -> approval gate -> dispatcher.apply -> audit log.
The same `state` + components are reused by the Streamlit UI in M7."""

from typing import Callable

from fleet.contracts.state import WorldState, ApprovalStatus, EventType
from fleet.factory import Components
from fleet.dispatch.approval import should_auto_approve
from fleet.dispatch.dispatcher import RESOLVE_ACTIONS
from fleet.routing.planner import plan_routes, reroute, plan_total_minutes


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
        events = []
        for e in state.get_active_events():
            if e.id in handled:
                continue
            
            # Filter out traffic/flood that is not on any active route
            if e.event_type in (EventType.TRAFFIC, EventType.FLOODED_AREA) and "->" in e.target:
                edge_id = e.target
                u, v = edge_id.split("->")
                u = u.split("#")[0]
                v = v.split("#")[0]

                is_on_route = False
                for vid, route in state.plan.items():
                    stops = sorted(route.stops, key=lambda st: st.sequence)
                    remaining_nodes = [st.customer_id for st in stops if st.actual_arrival is None]
                    if remaining_nodes:
                        from fleet.contracts.state import VehicleStatus
                        veh = state.vehicles.get(vid)
                        last_visited = "DEPOT"
                        if veh and veh.current_stop_index >= 0:
                            for st in stops:
                                if st.sequence == veh.current_stop_index:
                                    last_visited = st.customer_id
                                    break
                        full_remaining = [last_visited] + remaining_nodes + ["DEPOT"]
                        
                        for i in range(len(full_remaining) - 1):
                            r_u, r_v = full_remaining[i], full_remaining[i+1]
                            if (r_u == u and r_v == v) or (r_u == v and r_v == u):
                                is_on_route = True
                                break
                    if is_on_route:
                        break
                
                if not is_on_route:
                    continue # Skip this event, it's irrelevant

            events.append(e)

        severity_by_event = {e.id: e.severity for e in events}
        decisions = components.decision_engine.decide(state, events)

        needs_resolve = False
        resolve_decisions = []
        for d in decisions:
            state.decisions.append(d)
            severity = severity_by_event.get(d.event_id)
            if should_auto_approve(d, severity, settings):
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
