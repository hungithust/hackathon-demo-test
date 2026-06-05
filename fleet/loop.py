"""Headless orchestration loop (spec §7).

Each tick: simulator.tick -> detector.detect (+ active injected events) ->
decision_engine.decide -> approval gate -> dispatcher.apply -> audit log.
The same `state` + components are reused by the Streamlit UI in M7."""

from typing import Callable

from fleet.contracts.state import WorldState, ApprovalStatus
from fleet.factory import Components
from fleet.dispatch.approval import should_auto_approve
from fleet.routing.planner import plan_routes


def run_loop(state: WorldState, components: Components, n_ticks: int,
             settings, logger: Callable[..., None] = print) -> WorldState:
    if not state.plan and state.total_orders_pending() > 0:
        plan_routes(state, components.optimizer)
    for _ in range(n_ticks):
        components.simulator.tick(state)

        detected = components.detector.detect(state)
        active = list(state.get_active_events())
        events, seen = [], set()
        for e in detected + active:               # detector output + injected
            if e.id not in seen:
                seen.add(e.id)
                events.append(e)

        severity_by_event = {e.id: e.severity for e in events}
        decisions = components.decision_engine.decide(state, events)

        for d in decisions:
            state.decisions.append(d)
            severity = severity_by_event.get(d.event_id)
            if should_auto_approve(d, severity, settings):
                d.approval_status = ApprovalStatus.APPROVED
                d.approved_by = "auto"
                d.approved_at = state.clock
                components.dispatcher.apply(state, d)
                verdict = "AUTO-APPLIED"
            else:
                verdict = "QUEUED(approval)"
            logger(f"t={state.sim_tick} clock={state.clock} "
                   f"{d.action.value} <- {d.event_id} [{verdict}]")

        logger(f"t={state.sim_tick} clock={state.clock} "
               f"active_events={len(events)} pending={len(state.get_pending_decisions())}")
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
