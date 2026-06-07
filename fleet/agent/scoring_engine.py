"""Scoring-policy decision engine (M-D §6). For each event, enumerate candidate
actions, score each by a context cost (SLA-breach risk, added delay,
priority-weighted drops), and pick the cheapest — replacing the 1-to-1
event->action map with genuine trade-off evaluation. Deterministic, RNG-free.
Selected by DECISION_ENGINE=scoring; RuleBasedEngine stays the default/fallback
and its _ACTION_BY_EVENT map is untouched (Claude fallback / Sovereign-Brain
teacher depend on it)."""

from typing import Dict, List

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, Decision, DecisionAction,
    DecisionEngine,
)

_SEVERITY_WEIGHT = {
    EventSeverity.LOW: 1.0, EventSeverity.MEDIUM: 2.0,
    EventSeverity.HIGH: 3.0, EventSeverity.CRITICAL: 4.0,
}

# per-action heuristic effect: estimated added delay (min) and permanent order drops
_ACTION_EFFECT = {
    DecisionAction.REROUTE:      {"delay": 8.0,  "drops": 0.0},
    DecisionAction.RESCHEDULE:   {"delay": 20.0, "drops": 0.0},
    DecisionAction.REPRIORITIZE: {"delay": 3.0,  "drops": 0.0},
    DecisionAction.REALLOCATE:   {"delay": 12.0, "drops": 0.0},
    DecisionAction.DEFER:        {"delay": 60.0, "drops": 0.0},
    DecisionAction.ACCELERATE:   {"delay": 2.0,  "drops": 0.0},
    DecisionAction.CANCEL:       {"delay": 0.0,  "drops": 1.0},
}

_CANDIDATES = {
    EventType.TRAFFIC:            [DecisionAction.REROUTE, DecisionAction.RESCHEDULE, DecisionAction.DEFER],
    EventType.FLOODED_AREA:       [DecisionAction.REROUTE, DecisionAction.RESCHEDULE, DecisionAction.DEFER],
    EventType.DEMAND_SURGE:       [DecisionAction.REPRIORITIZE, DecisionAction.ACCELERATE, DecisionAction.REALLOCATE],
    EventType.URGENT_ORDER:       [DecisionAction.REPRIORITIZE, DecisionAction.ACCELERATE, DecisionAction.REALLOCATE],
    EventType.INVENTORY_SHORTAGE: [DecisionAction.DEFER, DecisionAction.REPRIORITIZE, DecisionAction.CANCEL],
    EventType.VEHICLE_BREAKDOWN:  [DecisionAction.REALLOCATE, DecisionAction.RESCHEDULE, DecisionAction.CANCEL],
}

_RESOLVES = {
    EventType.TRAFFIC:            {DecisionAction.REROUTE, DecisionAction.RESCHEDULE},
    EventType.FLOODED_AREA:       {DecisionAction.REROUTE, DecisionAction.RESCHEDULE},
    EventType.DEMAND_SURGE:       {DecisionAction.REPRIORITIZE, DecisionAction.ACCELERATE, DecisionAction.REALLOCATE},
    EventType.URGENT_ORDER:       {DecisionAction.REPRIORITIZE, DecisionAction.ACCELERATE, DecisionAction.REALLOCATE},
    EventType.INVENTORY_SHORTAGE: {DecisionAction.DEFER, DecisionAction.CANCEL},
    EventType.VEHICLE_BREAKDOWN:  {DecisionAction.REALLOCATE, DecisionAction.RESCHEDULE, DecisionAction.CANCEL},
}


def candidate_actions(event_type: EventType) -> List[DecisionAction]:
    return list(_CANDIDATES.get(event_type, [DecisionAction.REROUTE]))


def _resolves(event_type: EventType, action: DecisionAction) -> bool:
    return action in _RESOLVES.get(event_type, set())
