"""Decision engine over a self-hosted NVIDIA NIM (Sovereign Brain v2, M-C).

Same DecisionEngine interface and List[Decision] shape as ClaudeAgent/
RuleBasedEngine, so the loop/approval gate don't change. Reuses the pure
build_messages/parse_decision from claude_agent — only the transport differs,
and it is injected (built lazily from settings.nim_endpoint via the OpenAI-
compatible client) so the suite never imports openai or hits the network.
Per-event fallback to the rule-based action keeps the loop unbreakable."""

from typing import Callable, List

from fleet.contracts.state import (
    WorldState, Event, Decision, DecisionAction, DecisionEngine,
)
from fleet.agent.claude_agent import build_messages, parse_decision, _DECISION_SCHEMA
from fleet.agent.rule_based import _ACTION_BY_EVENT

_DEFAULT_ADDED_DELAY_MIN = 5.0


class NimAgent:
    """DecisionEngine backed by a self-hosted NIM.

    `complete(system, user) -> dict` is injected so the decide path is testable
    offline. When omitted, a lazy default transport is built from
    `settings.nim_endpoint` on first use (requires the optional `openai` package
    and a reachable endpoint)."""

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
                                          engine=DecisionEngine.LOCAL_NIM))
            except Exception:
                out.append(self._fallback(event, self._seq, state.clock))
        return out

    def _fallback(self, event: Event, seq: int, clock) -> Decision:
        """Rule-based action when the NIM call/parse fails — the loop always gets
        a decision per event. Reuses RuleBasedEngine's event->action map (DRY)."""
        action = _ACTION_BY_EVENT.get(event.event_type, DecisionAction.REROUTE)
        return Decision(
            id=f"DEC_{seq:03d}", timestamp=clock, event_id=event.id,
            action=action, engine=DecisionEngine.RULE_BASED,
            description=f"[nim->rule fallback] {event.event_type.value} "
                        f"on {event.target}",
            impact_estimate={"added_delay_min": _DEFAULT_ADDED_DELAY_MIN},
            reasoning="nim transport failed; used rule-based fallback",
        )

    def _get_complete(self) -> Callable[[str, str], dict]:
        if self._complete is None:
            self._complete = self._build_default_complete()
        return self._complete

    def _build_default_complete(self) -> Callable[[str, str], dict]:
        """Lazily build the OpenAI-compatible NIM transport. Imported here so the
        dependency is optional and tests never touch the network."""
        endpoint = getattr(self.settings, "nim_endpoint", "") or ""
        if not endpoint:
            raise RuntimeError(
                "NimAgent has no transport and settings.nim_endpoint is empty; "
                "configure an endpoint or inject a `complete` callable.")

        import json
        import requests

        model = getattr(self.settings, "nim_model", "") or ""

        def complete(system: str, user: str) -> dict:
            url = endpoint.rstrip("/") + "/chat/completions"
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "temperature": 0.0
            }
            # Only add guided decoding if it's explicitly a NIM model, but to be safe 
            # and universally compatible, we'll just ask for JSON via prompt structure.
            # The system prompt from claude_agent already strictly asks for JSON.
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            
            data = resp.json()
            
            # --- Added Logging ---
            print("\n" + "="*50)
            print("[NimAgent] RAW API RESPONSE FROM LOCAL MODEL:")
            print(json.dumps(data, indent=2))
            print("="*50 + "\n")
            # ---------------------
            
            content = data["choices"][0]["message"]["content"]
            
            # Clean up potential markdown fences
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
                
            return json.loads(content)

        return complete
