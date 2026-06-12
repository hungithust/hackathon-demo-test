from fleet.ui.controller import SimulationController


def test_controller_starts_at_tick_zero():
    c = SimulationController()
    snap = c.snapshot()
    assert snap["sim_tick"] == 0
    assert isinstance(snap["clock"], str)            # ISO string, not datetime
    assert snap["vehicles"]                          # sample world has vehicles
    assert "pending_orders" in snap


def test_step_advances_the_world():
    c = SimulationController()
    c.step(3)
    snap = c.snapshot()
    assert snap["sim_tick"] == 3
    # decision counters are present and consistent
    d = snap["decisions"]
    assert d["total"] == d["pending"] + d["approved"] + d["rejected"] + d["other"]


def test_snapshot_is_json_safe():
    import json
    c = SimulationController()
    c.step(1)
    json.dumps(c.snapshot())   # raises if any value isn't JSON-serializable


from fleet.contracts.state import (
    EventType, EventSeverity, ApprovalStatus, DecisionAction,
)


def _controller_with_pending_decision():
    """A CRITICAL breakdown -> REALLOCATE, which the gate always queues PENDING."""
    c = SimulationController()
    c.components.simulator.inject_event(
        c.state, EventType.VEHICLE_BREAKDOWN, "V001", EventSeverity.CRITICAL)
    c.step(1)
    pend = c.state.get_pending_decisions()
    assert pend, "expected at least one pending decision to approve/reject"
    return c, pend[0]


def test_approve_marks_executed_by_human():
    c, d = _controller_with_pending_decision()
    returned = c.approve(d.id)
    assert returned.approval_status == ApprovalStatus.APPROVED
    assert returned.approved_by == "human"
    assert returned.executed_at is not None
    assert d not in c.state.get_pending_decisions()


def test_reject_marks_rejected_not_executed():
    c, d = _controller_with_pending_decision()
    returned = c.reject(d.id)
    assert returned.approval_status == ApprovalStatus.REJECTED
    assert returned.approved_by == "human"
    assert returned.executed_at is None
    assert d not in c.state.get_pending_decisions()


def test_approve_unknown_id_raises():
    import pytest
    c = SimulationController()
    with pytest.raises(KeyError):
        c.approve("NOPE")


def test_approving_a_reroute_resolves_routes():
    # seed a concrete order so reroute has something to plan
    c = SimulationController()
    c.state.customers["C001"].orders = {"SKUX": 20}
    c.state.depot.inventory["SKUX"] = 200
    # dispatch the order first: under the gated model a reroute only re-solves
    # already-dispatched customers, so there must be a live route to reroute.
    c.dispatch_orders(["C001"])
    # a manual REROUTE decision sitting pending
    from fleet.contracts.state import Decision, DecisionEngine
    d = Decision(id="DEC_MANUAL", timestamp=c.state.clock, event_id=None,
                 action=DecisionAction.REROUTE, engine=DecisionEngine.HUMAN,
                 description="manual reroute", impact_estimate={"added_delay_min": 0.0})
    c.state.decisions.append(d)
    c.approve(d.id)
    assert c.state.plan        # reroute() wrote a fresh plan


def test_end_to_end_step_then_approve_flow():
    c, d = _controller_with_pending_decision()
    before = c.snapshot()
    assert before["decisions"]["pending"] >= 1
    c.approve(d.id)
    after = c.snapshot()
    assert after["decisions"]["pending"] == before["decisions"]["pending"] - 1
    assert after["decisions"]["approved"] == before["decisions"]["approved"] + 1
    # stepping further keeps the world consistent and JSON-safe
    import json
    c.step(2)
    json.dumps(c.snapshot())
    assert c.snapshot()["sim_tick"] == before["sim_tick"] + 2
