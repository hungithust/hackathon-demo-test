"""Rule-based decision engine (default). Emits one decision per event using a
fixed event->action map. M5 adds ClaudeAgent (ReAct + tool-calling) behind the
same DecisionEngine interface; this stays as the no-API-key fallback."""

from typing import List

from fleet.contracts.state import (
    WorldState, Event, EventType, Decision, DecisionAction, DecisionEngine,
)

_ACTION_BY_EVENT = {
    EventType.TRAFFIC: DecisionAction.REROUTE,
    EventType.FLOODED_AREA: DecisionAction.REROUTE,
    EventType.DEMAND_SURGE: DecisionAction.REPRIORITIZE,
    EventType.URGENT_ORDER: DecisionAction.REPRIORITIZE,
    EventType.INVENTORY_SHORTAGE: DecisionAction.DEFER,
    EventType.VEHICLE_BREAKDOWN: DecisionAction.REALLOCATE,
}


class RuleBasedEngine:
    def __init__(self):
        self._seq = 0

    def decide(self, state: WorldState, events: List[Event]) -> List[Decision]:
        out: List[Decision] = []
        for e in events:
            self._seq += 1
            action = _ACTION_BY_EVENT.get(e.event_type, DecisionAction.REROUTE)
            out.append(Decision(
                id=f"DEC_{self._seq:03d}", timestamp=state.clock, event_id=e.id,
                action=action, engine=DecisionEngine.RULE_BASED,
                description=f"[rule] respond to {e.event_type.value} on {e.target}",
                impact_estimate={"added_delay_min": 5.0},
                reasoning="rule-based event->action mapping (M1 stub)",
            ))
        return out
