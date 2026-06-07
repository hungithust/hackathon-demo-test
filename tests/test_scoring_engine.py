from datetime import datetime

from fleet.contracts.state import EventType, DecisionAction, Event, EventSeverity
from fleet.agent.scoring_engine import (
    candidate_actions, _resolves, score_action, _Weights,
)
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def _evt(etype, target, sev=EventSeverity.HIGH):
    return Event(id="E1", event_type=etype, target=target, severity=sev,
                 started_at=datetime(2026, 6, 7, 8, 0))


def test_candidates_per_event_type():
    assert DecisionAction.REROUTE in candidate_actions(EventType.FLOODED_AREA)
    assert DecisionAction.REALLOCATE in candidate_actions(EventType.VEHICLE_BREAKDOWN)
    assert len(candidate_actions(EventType.INVENTORY_SHORTAGE)) >= 2


def test_resolves_table():
    assert _resolves(EventType.FLOODED_AREA, DecisionAction.REROUTE) is True
    assert _resolves(EventType.FLOODED_AREA, DecisionAction.DEFER) is False
    assert _resolves(EventType.INVENTORY_SHORTAGE, DecisionAction.CANCEL) is True
    assert _resolves(EventType.INVENTORY_SHORTAGE, DecisionAction.REPRIORITIZE) is False


def test_resolving_action_cheaper_than_nonresolving():
    s = build_sample_state()
    w = _Weights(load_settings())
    e = _evt(EventType.FLOODED_AREA, "DEPOT->C001#2", EventSeverity.CRITICAL)
    reroute = score_action(s, e, DecisionAction.REROUTE, w)     # resolves
    defer = score_action(s, e, DecisionAction.DEFER, w)         # does not resolve
    assert reroute < defer


def test_lower_delay_resolving_action_preferred():
    s = build_sample_state()
    w = _Weights(load_settings())
    e = _evt(EventType.FLOODED_AREA, "DEPOT->C001#2")
    assert (score_action(s, e, DecisionAction.REROUTE, w)
            < score_action(s, e, DecisionAction.RESCHEDULE, w))


def test_priority_weight_scales_drop_cost():
    s = build_sample_state()
    w = _Weights(load_settings())
    # C001 has priority 1 (urgent); compare CANCEL cost for an urgent vs a fabricated low-prio customer
    s.customers["C001"].priority = 1
    s.customers["C002"].priority = 4
    e_urgent = _evt(EventType.INVENTORY_SHORTAGE, "C001")
    e_low = _evt(EventType.INVENTORY_SHORTAGE, "C002")
    assert (score_action(s, e_urgent, DecisionAction.CANCEL, w)
            > score_action(s, e_low, DecisionAction.CANCEL, w))
