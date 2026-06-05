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


class ClaudeAgent:
    """DecisionEngine backed by Claude (Anthropic SDK).

    `complete(system, user) -> dict` is injected so the decide path is testable
    offline. When omitted, a lazy default transport is built from
    `settings.anthropic_api_key` on first use (requires the optional `anthropic`
    package and a valid key)."""

    def __init__(self, settings=None,
                 complete: Callable[[str, str], dict] = None):
        self.settings = settings
        self._complete = complete
        self._seq = 0

    def decide(self, state: WorldState, events: List[Event]) -> List[Decision]:
        out: List[Decision] = []
        for event in events:
            self._seq += 1
            try:
                system, user = build_messages(state, event)
                data = self._get_complete()(system, user)
                out.append(parse_decision(data, event, self._seq, state.clock))
            except Exception:
                out.append(self._fallback(event, self._seq, state.clock))
        return out

    def _fallback(self, event: Event, seq: int, clock) -> Decision:
        """Rule-based action when the LLM call/parse fails — the loop always gets
        a decision per event. Reuses RuleBasedEngine's event->action map (DRY)."""
        action = _ACTION_BY_EVENT.get(event.event_type, DecisionAction.REROUTE)
        return Decision(
            id=f"DEC_{seq:03d}", timestamp=clock, event_id=event.id,
            action=action, engine=DecisionEngine.RULE_BASED,
            description=f"[claude->rule fallback] {event.event_type.value} "
                        f"on {event.target}",
            impact_estimate={"added_delay_min": _DEFAULT_ADDED_DELAY_MIN},
            reasoning="claude transport failed; used rule-based fallback",
        )

    def _get_complete(self) -> Callable[[str, str], dict]:
        if self._complete is None:
            self._complete = self._build_default_complete()
        return self._complete

    def _build_default_complete(self) -> Callable[[str, str], dict]:
        """Lazily build the real Anthropic transport. Imported here so the
        dependency is optional and tests never touch the network."""
        api_key = getattr(self.settings, "anthropic_api_key", "") or ""
        if not api_key:
            raise RuntimeError(
                "ClaudeAgent has no transport and settings.anthropic_api_key is "
                "empty; configure a key or inject a `complete` callable.")

        import anthropic  # optional dep

        client = anthropic.Anthropic(api_key=api_key)

        def complete(system: str, user: str) -> dict:
            resp = client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                thinking={"type": "adaptive"},
                system=system,
                output_config={"format": {"type": "json_schema",
                                          "schema": _DECISION_SCHEMA}},
                messages=[{"role": "user", "content": user}],
            )
            text = next(b.text for b in resp.content if b.type == "text")
            return json.loads(text)

        return complete
