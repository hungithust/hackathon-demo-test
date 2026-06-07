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


def _priority_weight(state: WorldState, event: Event) -> float:
    """Priority 1 (most urgent) -> 4; priority 4 -> 1; non-customer targets -> 2."""
    cust = state.customers.get(event.target)
    if cust is not None:
        return float(5 - int(cust.priority))
    return 2.0


class _Weights:
    def __init__(self, settings=None):
        self.sla = float(getattr(settings, "score_w_sla", 50.0) or 50.0)
        self.delay = float(getattr(settings, "score_w_delay", 1.0) or 1.0)
        self.drop = float(getattr(settings, "score_w_drop", 50.0) or 50.0)


def score_action(state: WorldState, event: Event, action: DecisionAction,
                 weights: "_Weights") -> float:
    """Lower is better. Cost = delay + priority-weighted drops + SLA penalty when
    the action does NOT resolve the disruption (penalty scales with severity)."""
    eff = _ACTION_EFFECT[action]
    cost = weights.delay * max(0.0, eff["delay"])
    cost += weights.drop * eff["drops"] * _priority_weight(state, event)
    if not _resolves(event.event_type, action):
        cost += weights.sla * _SEVERITY_WEIGHT.get(event.severity, 2.0)
    return cost
