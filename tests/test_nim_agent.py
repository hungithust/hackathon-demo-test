import pytest

from config.settings import load_settings
from fleet.contracts.state import (
    DecisionEngine, DecisionAction, Event, EventType, EventSeverity,
)
from fleet.scenarios import build_sample_state


def _event(event_type, target, severity, clock):
    return Event(id="E1", event_type=event_type, target=target,
                 severity=severity, started_at=clock)


def test_nim_agent_decide_parses_and_tags_local_nim():
    from fleet.agent.nim_agent import NimAgent
    state = build_sample_state()
    evt = _event(EventType.TRAFFIC, "e1", EventSeverity.MEDIUM, state.clock)

    def fake_complete(system, user):
        return {"action": "reroute", "reasoning": "avoid congestion",
                "added_delay_min": 8}

    [d] = NimAgent(settings=None, complete=fake_complete).decide(state, [evt])
    assert d.action == DecisionAction.REROUTE
    assert d.engine == DecisionEngine.LOCAL_NIM
    assert d.reasoning == "avoid congestion"
    assert d.impact_estimate["added_delay_min"] == 8.0


def test_nim_agent_falls_back_to_rule_on_transport_error():
    from fleet.agent.nim_agent import NimAgent
    state = build_sample_state()
    evt = _event(EventType.VEHICLE_BREAKDOWN, "V001", EventSeverity.CRITICAL, state.clock)

    def boom(system, user):
        raise RuntimeError("endpoint down")

    [d] = NimAgent(settings=None, complete=boom).decide(state, [evt])
    assert d.engine == DecisionEngine.RULE_BASED              # demo never hard-fails
    assert d.action == DecisionAction.REALLOCATE             # rule map for breakdown


def test_nim_agent_build_default_complete_requires_endpoint():
    from fleet.agent.nim_agent import NimAgent
    agent = NimAgent(settings=load_settings({}))             # no endpoint, no transport
    with pytest.raises(RuntimeError, match="nim_endpoint is empty"):
        agent._build_default_complete()                      # raises before importing openai
