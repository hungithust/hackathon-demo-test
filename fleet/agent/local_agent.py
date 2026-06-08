"""Decision engine over a local API (e.g. vLLM or similar).

Same DecisionEngine interface and List[Decision] shape as ClaudeAgent.
Uses raw HTTP requests instead of the openai SDK to hit the v1/chat/completions endpoint.
"""
import json
import requests
from typing import Callable, List

from fleet.contracts.state import (
    WorldState, Event, Decision, DecisionAction, DecisionEngine,
)
from fleet.agent.claude_agent import build_messages, parse_decision
from fleet.agent.rule_based import _ACTION_BY_EVENT

_DEFAULT_ADDED_DELAY_MIN = 5.0


class LocalAgent:
    """DecisionEngine backed by a generic local API.

    `complete(system, user) -> dict` is injected so the decide path is testable
    offline. When omitted, a lazy default transport is built from
    `settings.local_endpoint` on first use."""

    def __init__(self, settings=None, complete: Callable[[str, str], dict] = None):
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
                out.append(parse_decision(data, event, self._seq, state.clock,
                                          engine=DecisionEngine.LOCAL_API))
            except Exception:
                out.append(self._fallback(event, self._seq, state.clock))
        return out

    def _fallback(self, event: Event, seq: int, clock) -> Decision:
        action = _ACTION_BY_EVENT.get(event.event_type, DecisionAction.REROUTE)
        return Decision(
            id=f"DEC_{seq:03d}", timestamp=clock, event_id=event.id,
            action=action, engine=DecisionEngine.RULE_BASED,
            description=f"[local->rule fallback] {event.event_type.value} "
                        f"on {event.target}",
            impact_estimate={"added_delay_min": _DEFAULT_ADDED_DELAY_MIN},
            reasoning="local api transport failed; used rule-based fallback",
        )

    def _get_complete(self) -> Callable[[str, str], dict]:
        if self._complete is None:
            self._complete = self._build_default_complete()
        return self._complete

    def _build_default_complete(self) -> Callable[[str, str], dict]:
        endpoint = getattr(self.settings, "local_endpoint", "") or ""
        if not endpoint:
            raise RuntimeError(
                "LocalAgent has no transport and settings.local_endpoint is empty; "
                "configure an endpoint or inject a `complete` callable.")

        model = getattr(self.settings, "local_model", "") or "sovereign-brain"

        def complete(system: str, user: str) -> dict:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "max_tokens": 500,
                "temperature": 0.0
            }
            resp = requests.post(endpoint, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            answer = result["choices"][0]["message"]["content"]
            
            clean_answer = answer.strip()
            if clean_answer.startswith("```json"):
                clean_answer = clean_answer[7:]
            if clean_answer.startswith("```"):
                clean_answer = clean_answer[3:]
            if clean_answer.endswith("```"):
                clean_answer = clean_answer[:-3]
                
            return json.loads(clean_answer.strip())

        return complete
