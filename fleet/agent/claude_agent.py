"""LLM decision engine: asks Claude which DecisionAction to take per event.

Same DecisionEngine interface and List[Decision] shape as RuleBasedEngine, so the
loop/approval gate don't change. The prompt builder and parser are pure and fully
unit-tested with canned JSON; the Anthropic transport is injected (and created
lazily) so no API key/network is needed to run the suite. Falls back to the
rule-based action per event if a call fails.

Anthropic SDK: claude-opus-4-8, adaptive thinking, output_config.format
structured outputs (per the claude-api skill).
"""

import json
from typing import Callable, Dict, List, Tuple

from fleet.contracts.state import (
    WorldState, Event, Decision, DecisionAction, DecisionEngine,
)
from fleet.agent.rule_based import _ACTION_BY_EVENT

_MODEL = "claude-opus-4-8"
_DEFAULT_ADDED_DELAY_MIN = 5.0

_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [a.value for a in DecisionAction],
            "description": "The dispatch action to take in response to the event.",
        },
        "reasoning": {
            "type": "string",
            "description": "One or two sentences justifying the action.",
        },
        "added_delay_min": {
            "type": "number",
            "description": "Estimated added delay in minutes this action introduces.",
        },
    },
    "required": ["action", "reasoning", "added_delay_min"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are the decision engine for a real-time delivery-fleet dispatch system "
    "(single depot, vehicles serving customers under time windows). For each "
    "disruption event you are given, choose exactly one dispatch action that best "
    "protects on-time delivery and safety, and estimate the delay it adds. "
    "Available actions: "
    + ", ".join(a.value for a in DecisionAction)
    + ". Respond using the provided JSON schema only."
)


def build_messages(state: WorldState, event: Event) -> Tuple[str, str]:
    """Return (system, user) prompt strings for one event. Pure: deterministic
    given state+event, no timestamps injected beyond the event's own facts."""
    pending = state.total_orders_pending()
    n_vehicles = len(state.vehicles)
    user = (
        f"Event type: {event.event_type.value}\n"
        f"Target: {event.target}\n"
        f"Severity: {event.severity.value}\n"
        f"Description: {event.description}\n"
        f"Fleet size: {n_vehicles} vehicles; pending order units: {pending}.\n"
        "Choose the single best dispatch action and estimate added delay (minutes)."
    )
    return _SYSTEM, user


def parse_decision(data: dict, event: Event, seq: int, clock) -> Decision:
    """Map one model JSON object to a Decision. Raises ValueError if `action`
    is not a valid DecisionAction value (caller decides how to recover)."""
    action = DecisionAction(data["action"])   # raises ValueError on unknown
    added_delay = float(data.get("added_delay_min", _DEFAULT_ADDED_DELAY_MIN))
    return Decision(
        id=f"DEC_{seq:03d}", timestamp=clock, event_id=event.id,
        action=action, engine=DecisionEngine.CLAUDE,
        description=f"[claude] respond to {event.event_type.value} on {event.target}",
        impact_estimate={"added_delay_min": added_delay},
        reasoning=str(data.get("reasoning", "")),
    )
