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
    EventType.ROAD_BLOCK:         [DecisionAction.REROUTE, DecisionAction.RESCHEDULE, DecisionAction.DEFER],
    EventType.ACCIDENT:           [DecisionAction.REROUTE, DecisionAction.RESCHEDULE, DecisionAction.DEFER],
    EventType.FLOODED_AREA:       [DecisionAction.REROUTE, DecisionAction.RESCHEDULE, DecisionAction.DEFER],
    EventType.DEMAND_SURGE:       [DecisionAction.REPRIORITIZE, DecisionAction.ACCELERATE, DecisionAction.REALLOCATE],
    EventType.URGENT_ORDER:       [DecisionAction.REPRIORITIZE, DecisionAction.ACCELERATE, DecisionAction.REALLOCATE],
    EventType.INVENTORY_SHORTAGE: [DecisionAction.DEFER, DecisionAction.REPRIORITIZE, DecisionAction.CANCEL],
    EventType.VEHICLE_BREAKDOWN:  [DecisionAction.REALLOCATE, DecisionAction.RESCHEDULE, DecisionAction.CANCEL],
}

_RESOLVES = {
    EventType.TRAFFIC:            {DecisionAction.REROUTE, DecisionAction.RESCHEDULE},
    EventType.ROAD_BLOCK:         {DecisionAction.REROUTE, DecisionAction.RESCHEDULE},
    EventType.ACCIDENT:           {DecisionAction.REROUTE, DecisionAction.RESCHEDULE},
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


class ScoringEngine:
    def __init__(self, settings=None):
        self.settings = settings
        self.weights = _Weights(settings)
        self.enable_proactive = bool(getattr(settings, "enable_proactive", False))
        self._seq = 0
        self._proactive_emitted: set = set()

    def decide(self, state: WorldState, events: List[Event]) -> List[Decision]:
        out: List[Decision] = []
        for e in events:
            scored = sorted(
                ((a, score_action(state, e, a, self.weights))
                 for a in candidate_actions(e.event_type)),
                key=lambda t: (t[1], t[0].value))      # min cost, stable tie-break
            best, cost = scored[0]
            self._seq += 1
            impact: Dict[str, float] = {
                f"score_{a.value}": round(c, 2) for a, c in scored}
            impact["added_delay_min"] = float(max(0.0, _ACTION_EFFECT[best]["delay"]))
            alts = ", ".join(f"{a.value}={c:.1f}" for a, c in scored[1:])
            out.append(Decision(
                id=f"DEC_{self._seq:03d}", timestamp=state.clock, event_id=e.id,
                action=best, engine=DecisionEngine.RULE_BASED,
                description=f"[scoring] {e.event_type.value} on {e.target}",
                impact_estimate=impact,
                reasoning=f"chose {best.value} (cost {cost:.1f}) over {alts}",
            ))
        if self.enable_proactive:
            out.extend(self._proactive(state))
        return out

    def _proactive(self, state: WorldState) -> List[Decision]:
        """Pre-empt shortfalls: if total pending for a SKU exceeds depot stock,
        the customers ordering it are at risk -> emit one reprioritize each
        (deduped until the shortfall clears). State-projection version of the
        forecaster proactive signal (§6.2); fully deterministic."""
        pending: Dict[str, int] = {}
        for c in state.customers.values():
            for sku, qty in c.orders.items():
                pending[sku] = pending.get(sku, 0) + qty
        short = {sku for sku, q in pending.items()
                 if q > state.depot.inventory.get(sku, 0)}
        out: List[Decision] = []
        for cid in sorted(state.customers):
            cust = state.customers[cid]
            at_risk = any(sku in short for sku in cust.orders)
            if at_risk and cid not in self._proactive_emitted:
                self._proactive_emitted.add(cid)
                out.append(Decision(
                    id=f"DEC_PROACTIVE_{cid}", timestamp=state.clock, event_id=None,
                    action=DecisionAction.REPRIORITIZE,
                    engine=DecisionEngine.RULE_BASED,
                    description=f"[scoring] proactive: {cid} at risk of shortfall",
                    impact_estimate={"added_delay_min": 0.0},
                    reasoning=("stock projection shows this customer may not be fully "
                               "served; reprioritize ahead of the shortfall"),
                ))
            elif not at_risk:
                self._proactive_emitted.discard(cid)
        return out
