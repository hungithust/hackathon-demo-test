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


from fleet.agent.claude_agent import parse_decision
from fleet.contracts.state import DecisionEngine


def test_parse_decision_maps_fields():
    d = parse_decision(
        {"action": "reroute", "reasoning": "avoid the flooded edge",
         "added_delay_min": 8},
        event=_event(), seq=1, clock=datetime(2026, 6, 4, 7, 5),
    )
    assert d.id == "DEC_001"
    assert d.event_id == "EVT_001"
    assert d.action == DecisionAction.REROUTE
    assert d.engine == DecisionEngine.CLAUDE
    assert d.reasoning == "avoid the flooded edge"
    assert d.impact_estimate["added_delay_min"] == 8.0
    assert d.timestamp == datetime(2026, 6, 4, 7, 5)


def test_parse_decision_rejects_unknown_action():
    import pytest
    with pytest.raises(ValueError):
        parse_decision(
            {"action": "teleport", "reasoning": "x", "added_delay_min": 1},
            event=_event(), seq=2, clock=datetime(2026, 6, 4, 7, 5),
        )


from fleet.agent.claude_agent import ClaudeAgent


def test_decide_uses_transport_and_returns_decisions():
    state = build_sample_state()
    calls = []

    def fake_complete(system, user):
        calls.append((system, user))
        return {"action": "reroute", "reasoning": "flood detour",
                "added_delay_min": 12}

    agent = ClaudeAgent(settings=None, complete=fake_complete)
    decisions = agent.decide(state, [_event()])

    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == DecisionAction.REROUTE
    assert d.engine == DecisionEngine.CLAUDE
    assert d.reasoning == "flood detour"
    assert calls and "DEPOT->C001" in calls[0][1]


def test_decide_falls_back_to_rule_action_on_transport_error():
    state = build_sample_state()

    def boom(system, user):
        raise RuntimeError("api down")

    agent = ClaudeAgent(settings=None, complete=boom)
    decisions = agent.decide(state, [_event()])

    assert len(decisions) == 1
    d = decisions[0]
    # FLOODED_AREA -> REROUTE per the rule-based map; tagged as the fallback engine
    assert d.action == DecisionAction.REROUTE
    assert d.engine == DecisionEngine.RULE_BASED
    assert d.event_id == "EVT_001"


def test_decide_no_events_returns_empty():
    agent = ClaudeAgent(settings=None, complete=lambda s, u: {})
    assert agent.decide(build_sample_state(), []) == []
