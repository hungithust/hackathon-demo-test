from datetime import datetime

from fleet.contracts.state import (
    Decision, DecisionAction, DecisionEngine, EventSeverity,
)
from fleet.dispatch.approval import should_auto_approve
from config.settings import load_settings

S = load_settings()


def _dec(action, added_delay=5.0):
    return Decision(id="D", timestamp=datetime(2026, 6, 4, 7), event_id="E",
                    action=action, engine=DecisionEngine.RULE_BASED, description="",
                    impact_estimate={"added_delay_min": added_delay})


def test_small_reroute_auto_approved():
    assert should_auto_approve(_dec(DecisionAction.REROUTE, 5.0),
                               EventSeverity.LOW, S) is True


def test_large_reroute_needs_approval():
    assert should_auto_approve(_dec(DecisionAction.REROUTE, 25.0),
                               EventSeverity.LOW, S) is False


def test_defer_and_cancel_and_reallocate_need_approval():
    for a in (DecisionAction.DEFER, DecisionAction.CANCEL, DecisionAction.REALLOCATE):
        assert should_auto_approve(_dec(a), EventSeverity.LOW, S) is False


def test_critical_severity_always_needs_approval():
    assert should_auto_approve(_dec(DecisionAction.REROUTE, 5.0),
                               EventSeverity.CRITICAL, S) is False
