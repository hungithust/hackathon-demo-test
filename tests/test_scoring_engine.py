from fleet.contracts.state import EventType, DecisionAction
from fleet.agent.scoring_engine import candidate_actions, _resolves


def test_candidates_per_event_type():
    assert DecisionAction.REROUTE in candidate_actions(EventType.FLOODED_AREA)
    assert DecisionAction.REALLOCATE in candidate_actions(EventType.VEHICLE_BREAKDOWN)
    assert len(candidate_actions(EventType.INVENTORY_SHORTAGE)) >= 2


def test_resolves_table():
    assert _resolves(EventType.FLOODED_AREA, DecisionAction.REROUTE) is True
    assert _resolves(EventType.FLOODED_AREA, DecisionAction.DEFER) is False
    assert _resolves(EventType.INVENTORY_SHORTAGE, DecisionAction.CANCEL) is True
    assert _resolves(EventType.INVENTORY_SHORTAGE, DecisionAction.REPRIORITIZE) is False
