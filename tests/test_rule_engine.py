from datetime import datetime

from fleet.contracts.interfaces import DecisionEngine
from fleet.contracts.state import (
    Event, EventType, EventSeverity, DecisionAction, DecisionEngine as Eng,
)
from fleet.agent.rule_based import RuleBasedEngine
from fleet.scenarios import build_sample_state


def _evt(et, sev="low"):
    return Event(id="E1", event_type=et, target="DEPOT->C001",
                 severity=EventSeverity(sev), started_at=datetime(2026, 6, 4, 7))


def test_conforms_to_protocol():
    assert isinstance(RuleBasedEngine(), DecisionEngine)


def test_no_events_no_decisions():
    assert RuleBasedEngine().decide(build_sample_state(), []) == []


def test_traffic_maps_to_reroute():
    decs = RuleBasedEngine().decide(build_sample_state(), [_evt(EventType.TRAFFIC)])
    assert len(decs) == 1
    assert decs[0].action == DecisionAction.REROUTE
    assert decs[0].engine == Eng.RULE_BASED
    assert decs[0].event_id == "E1"


def test_breakdown_maps_to_reallocate():
    decs = RuleBasedEngine().decide(build_sample_state(),
                                    [_evt(EventType.VEHICLE_BREAKDOWN)])
    assert decs[0].action == DecisionAction.REALLOCATE
