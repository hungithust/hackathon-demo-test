from datetime import datetime

from fleet.contracts.state import (
    Event, EventType, EventSeverity, DecisionAction,
)
from fleet.scenarios import build_sample_state
from fleet.agent.claude_agent import build_messages, _DECISION_SCHEMA


def _event():
    return Event(
        id="EVT_001", event_type=EventType.FLOODED_AREA, target="DEPOT->C001",
        severity=EventSeverity.HIGH, started_at=datetime(2026, 6, 4, 7, 0),
        description="flood on DEPOT->C001",
    )


def test_build_messages_returns_system_and_user():
    state = build_sample_state()
    system, user = build_messages(state, _event())
    assert isinstance(system, str) and isinstance(user, str)
    # system frames the role
    assert "dispatch" in system.lower()
    # user carries the concrete event facts the model must reason over
    assert "flooded_area" in user.lower()
    assert "DEPOT->C001" in user
    assert "high" in user.lower()


def test_decision_schema_enumerates_all_actions():
    actions = _DECISION_SCHEMA["properties"]["action"]["enum"]
    assert set(actions) == {a.value for a in DecisionAction}
    # strict structured-output schema
    assert _DECISION_SCHEMA["additionalProperties"] is False
    assert set(_DECISION_SCHEMA["required"]) == {"action", "reasoning",
                                                 "added_delay_min"}
