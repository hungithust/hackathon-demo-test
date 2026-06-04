from datetime import timedelta

from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.loop import run_loop
from fleet.contracts.state import EventType, EventSeverity, DecisionAction, ApprovalStatus
from config.settings import load_settings


def _silent(*_args, **_kw):
    pass


def test_loop_advances_clock():
    s = build_sample_state()
    settings = load_settings(env={"TICK_MINUTES": "5"})
    comps = build_components(settings)
    start = s.clock
    run_loop(s, comps, n_ticks=3, settings=settings, logger=_silent)
    assert s.sim_tick == 3
    assert s.clock == start + timedelta(minutes=15)


def test_low_severity_event_flows_to_dispatched_decision():
    s = build_sample_state()
    settings = load_settings()
    comps = build_components(settings)
    comps.simulator.inject_event(s, EventType.TRAFFIC, "DEPOT->C001",
                                 EventSeverity.LOW)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    assert len(s.decisions) == 1
    d = s.decisions[-1]
    assert d.action == DecisionAction.REROUTE
    assert d.approval_status == ApprovalStatus.APPROVED
    assert d.approved_by == "auto"
    assert d.executed_at is not None


def test_critical_event_is_queued_not_executed():
    s = build_sample_state()
    settings = load_settings()
    comps = build_components(settings)
    comps.simulator.inject_event(s, EventType.VEHICLE_BREAKDOWN, "V001",
                                 EventSeverity.CRITICAL)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    d = s.decisions[-1]
    assert d.approval_status == ApprovalStatus.PENDING
    assert d.executed_at is None
    assert d in s.get_pending_decisions()
