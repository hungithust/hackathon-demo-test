"""Approval gate policy (spec §6.6). Auto-execute only small REROUTE/RESCHEDULE;
escalate DEFER/CANCEL/REALLOCATE (and anything CRITICAL) to a human queue."""

from typing import Optional

from fleet.contracts.state import Decision, DecisionAction, EventSeverity

_NEEDS_APPROVAL_ACTIONS = {
    DecisionAction.DEFER,
    DecisionAction.CANCEL,
    DecisionAction.REALLOCATE,
}
_AUTO_CANDIDATE_ACTIONS = {
    DecisionAction.REROUTE,
    DecisionAction.RESCHEDULE,
}


def should_auto_approve(decision: Decision,
                        severity: Optional[EventSeverity],
                        settings) -> bool:
    if severity == EventSeverity.CRITICAL:
        return False
    if decision.action in _NEEDS_APPROVAL_ACTIONS:
        return False
    if decision.action in _AUTO_CANDIDATE_ACTIONS:
        added = decision.impact_estimate.get("added_delay_min", 0.0)
        return added <= settings.auto_approve_delay_threshold_min
    return False  # REPRIORITIZE / ACCELERATE etc. default to manual
