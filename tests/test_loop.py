from datetime import timedelta

from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.loop import run_loop
from fleet.contracts.state import (
    EventType, EventSeverity, DecisionAction, ApprovalStatus, EdgeStatus,
)
import fleet.loop as loop_module
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
    evt = comps.simulator.inject_event(s, EventType.TRAFFIC, "DEPOT->C001",
                                       EventSeverity.LOW)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    # the simulator may raise its own events (shortages); target only ours.
    mine = [d for d in s.decisions if d.event_id == evt.id]
    assert len(mine) == 1
    d = mine[0]
    assert d.action == DecisionAction.REROUTE
    assert d.approval_status == ApprovalStatus.APPROVED
    assert d.approved_by == "auto"
    assert d.executed_at is not None


def test_critical_event_is_queued_not_executed():
    s = build_sample_state()
    settings = load_settings()
    comps = build_components(settings)
    evt = comps.simulator.inject_event(s, EventType.VEHICLE_BREAKDOWN, "V001",
                                       EventSeverity.CRITICAL)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    mine = [d for d in s.decisions if d.event_id == evt.id]
    assert len(mine) == 1
    d = mine[0]
    assert d.approval_status == ApprovalStatus.PENDING
    assert d.executed_at is None
    assert d in s.get_pending_decisions()


def test_loop_world_comes_alive_over_many_ticks():
    s = build_sample_state()
    settings = load_settings(env={"TICK_MINUTES": "30",
                                  "RESTOCK_INTERVAL_MIN": "100000"})
    comps = build_components(settings)
    run_loop(s, comps, n_ticks=20, settings=settings, logger=_silent)
    assert s.sim_tick == 20
    # the loop planned routes and at least one stop was actually visited
    assert s.plan
    assert any(st.actual_arrival is not None
               for r in s.plan.values() for st in r.stops)


def test_loop_plans_and_moves_vehicles():
    s = build_sample_state()
    # seed a concrete order so there is something to plan + deliver
    s.customers["C001"].orders = {"SKUX": 20}
    s.depot.inventory["SKUX"] = 200
    settings = load_settings(env={"TICK_MINUTES": "15"})
    comps = build_components(settings)
    run_loop(s, comps, n_ticks=8, settings=settings, logger=_silent)
    assert s.plan                                   # initial plan was built
    visited = [st for r in s.plan.values() for st in r.stops
               if st.actual_arrival is not None]
    assert visited                                  # at least one delivery happened


def test_standing_flood_does_not_re_fire_every_tick():
    # Regression: the sample world ships permanently flooded parallel edges. The
    # detector used to re-emit FLOODED_AREA every tick -> a fresh REROUTE that
    # wiped the in-progress plan, so vehicles never delivered. With event-lifecycle
    # reconciliation the standing condition is ONE persistent event / ONE decision.
    s = build_sample_state()                      # NOTE: no _heal_sample_floods
    settings = load_settings(env={"TICK_MINUTES": "30"})
    comps = build_components(settings)
    run_loop(s, comps, n_ticks=20, settings=settings, logger=_silent)

    reroutes = [d for d in s.decisions if d.action == DecisionAction.REROUTE]
    assert len(reroutes) <= 2                      # not 1-per-tick (was 40)
    # the world actually progresses: at least one real delivery happened
    assert any(st.actual_arrival is not None
               for r in s.plan.values() for st in r.stops)
    # every decision references an event that exists in the log (coherent timeline)
    event_ids = {e.id for e in s.events}
    assert all(d.event_id in event_ids
               for d in s.decisions if d.event_id is not None)


def test_loop_reroutes_on_edge_disruption(monkeypatch):
    s = build_sample_state()
    s.customers["C001"].orders = {"SKUX": 20}
    s.depot.inventory["SKUX"] = 200
    settings = load_settings()
    comps = build_components(settings)

    calls = {"n": 0}
    orig = loop_module.reroute

    def _spy(*args, **kwargs):
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(loop_module, "reroute", _spy, raising=False)

    # flood the depot->C001 link: FLOODED_AREA -> RuleBasedEngine REROUTE -> auto-approve
    comps.simulator.disrupt_edge(s, "DEPOT->C001", EdgeStatus.FLOODED,
                                 flood_level=0.9)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    reroutes = [d for d in s.decisions
                if d.action == DecisionAction.REROUTE
                and d.approval_status == ApprovalStatus.APPROVED]
    assert reroutes                       # the loop produced + approved a reroute
    assert calls["n"] > 0                 # the loop actually re-solved


def test_periodic_replan_reduces_backlog():
    # Without periodic replanning the fleet plans once, so demand the first plan
    # didn't cover piles up forever. With a replan cadence the loop keeps
    # absorbing fresh demand, so the standing backlog is much smaller.
    def _run(interval):
        s = build_sample_state()
        settings = load_settings(env={"TICK_MINUTES": "30",
                                      "REPLAN_INTERVAL_TICKS": interval,
                                      "RESTOCK_INTERVAL_MIN": "30"})
        comps = build_components(settings)
        run_loop(s, comps, n_ticks=12, settings=settings, logger=_silent)
        return s.total_orders_pending()

    assert _run("1") < _run("0")
