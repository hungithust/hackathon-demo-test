# M5 — ClaudeAgent (Claude behind DecisionEngine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second `DecisionEngine` implementation — `ClaudeAgent` — that asks Claude (via the official Anthropic SDK, structured outputs) which `DecisionAction` to take for each event, so the decision engine is swappable from rule-based to LLM-driven by config alone, with a safe fallback to `RuleBasedEngine` when no API key is configured (and per-event fallback if a call fails).

**Architecture:** The agent is two **pure, fully-testable functions** (`build_messages`: `(state, event)` → `(system, user)` prompt; `parse_decision`: model JSON → `Decision`) plus a thin `ClaudeAgent.decide` that wires them around an **injected transport** callable (`complete(system, user) -> dict`). Tests drive the pure functions and `decide` with canned JSON, so **no API key and no network are needed**. The real transport (Anthropic SDK, `claude-opus-4-8`, adaptive thinking, `output_config.format` structured outputs) is created lazily and only used at runtime when `anthropic_api_key` is set.

**Tech Stack:** Python 3.10+, dataclasses, pytest. Optional runtime-only dependency: `anthropic` (official SDK) — imported lazily, **not** required for tests. Same repo/venv/branch.

---

## Context

- Continues branch **`feat/base-project`** (plans 1–7: M0–M4 complete & green; 106 passing after M4).
- Implements the M5 milestone: "ClaudeAgent behind the `DecisionEngine` interface (LLM-driven decisions plug in beside `RuleBasedEngine`, selected by `config/settings.py`; default stays rule-based with no API key)."
- The `DecisionEngine` Protocol (`fleet/contracts/interfaces.py`) is a single method `decide(state, events) -> List[Decision]`. `RuleBasedEngine` already implements it; `ClaudeAgent` must produce the **same** `List[Decision]` shape so the loop/approval gate are unchanged.
- `config/settings.py` already has `decision_engine: str = "rule"  # rule | claude` and `anthropic_api_key: str = ""`. The factory currently falls `claude` back to `RuleBasedEngine` (TODO M5). This plan removes that TODO.

**Verified facts from the current code:**
- `RuleBasedEngine.decide` (in `fleet/agent/rule_based.py`) emits one `Decision` per event using `_ACTION_BY_EVENT` (a dict mapping `EventType` → `DecisionAction`, default `REROUTE`), with `impact_estimate={"added_delay_min": 5.0}` and `engine=DecisionEngine.RULE_BASED`. We reuse `_ACTION_BY_EVENT` for the fallback path (DRY).
- `Decision(id, timestamp, event_id, action, engine, description, impact_estimate={}, approval_status=PENDING, ..., reasoning="")`.
- `DecisionEngine` enum: `RULE_BASED="rule_based"`, `CLAUDE="claude"`, `HUMAN="human"`.
- `DecisionAction` enum values are **lowercase**: `reroute`, `reschedule`, `reprioritize`, `reallocate`, `defer`, `cancel`, `accelerate`. So `DecisionAction(value)` round-trips a lowercase string directly — the structured-output schema uses these exact values as its `enum`.
- `Event(id, event_type, target, severity, started_at, description, metrics, ended_at)`; `EventSeverity` and `EventType` are `str` enums (`.value` is a string). The approval gate (`fleet/dispatch/approval.py`) reads `decision.impact_estimate["added_delay_min"]`, so the agent must populate it.

**Anthropic SDK usage (per the claude-api skill — grounded, not guessed):**
- Model **`claude-opus-4-8`**; adaptive thinking `thinking={"type": "adaptive"}` (do NOT use `budget_tokens` — removed on Opus 4.8).
- Structured outputs via `output_config={"format": {"type": "json_schema", "schema": _DECISION_SCHEMA}}` (the canonical API parameter; the deprecated top-level `output_format` is not used). Every object in the schema sets `additionalProperties: false` and lists all keys in `required`.
- Non-streaming `client.messages.create(...)` with `max_tokens=1024` (small structured reply, well under the SDK's streaming-required threshold).
- The response's first text block is valid JSON (guaranteed by `output_config.format`); parse with `json.loads`.

**Modeling decisions (documented in code):**
- **One call per event** (mirrors `RuleBasedEngine` one-decision-per-event), keeping the event→decision mapping unambiguous and easy to test. Batching all events into a single call is a future optimization, noted in a comment.
- The decision schema is `{action: <enum>, reasoning: string, added_delay_min: number}`. `action` maps directly to `DecisionAction`; `reasoning` → `Decision.reasoning`; `added_delay_min` → `impact_estimate` (so the existing approval gate works unchanged).
- **Resilience:** if the transport raises (network/quota/parse error) for an event, `decide` falls back to the rule-based action for that event (`_ACTION_BY_EVENT`) rather than dropping it — the loop always gets a decision per event. The fallback decision is tagged `engine=DecisionEngine.RULE_BASED` and its `reasoning` notes the fallback.
- `engine=DecisionEngine.CLAUDE` on successful LLM decisions.

**Changes:** new `fleet/agent/claude_agent.py`, new `tests/test_claude_agent.py`, modify `fleet/factory.py` (select `ClaudeAgent`), modify `tests/test_factory.py` (selection assertions), modify `requirements.txt` (document the optional dep as a comment).

Environment reminder (Windows / PowerShell): activate venv `.\.venv\Scripts\Activate.ps1`; run tests `pytest -v`; commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Only `git add` the files named in each task — do NOT touch `Guide.md`, `problem.txt`, `docs/PROBLEM_STATEMENT.md`.

---

### Task 1: Pure prompt builder + decision schema

**Files:**
- Create: `fleet/agent/claude_agent.py`
- Test: new `tests/test_claude_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_claude_agent.py`:
```python
from datetime import datetime

from fleet.contracts.state import (
    Event, EventType, EventSeverity, DecisionAction,
)
from fleet.scenarios import build_sample_state
from fleet.agent.claude_agent import build_messages, _DECISION_SCHEMA


def _event():
    return Event(
        id="EVT_001", event_type=EventType.FLOODED_AREA, target="DEPOT->C001",
        severity=EventSeverity.HIGH, started_at=datetime(2026, 6, 4, 7, 0),
        description="flood on DEPOT->C001",
    )


def test_build_messages_returns_system_and_user():
    state = build_sample_state()
    system, user = build_messages(state, _event())
    assert isinstance(system, str) and isinstance(user, str)
    # system frames the role
    assert "dispatch" in system.lower()
    # user carries the concrete event facts the model must reason over
    assert "flooded_area" in user.lower()
    assert "DEPOT->C001" in user
    assert "high" in user.lower()


def test_decision_schema_enumerates_all_actions():
    actions = _DECISION_SCHEMA["properties"]["action"]["enum"]
    assert set(actions) == {a.value for a in DecisionAction}
    # strict structured-output schema
    assert _DECISION_SCHEMA["additionalProperties"] is False
    assert set(_DECISION_SCHEMA["required"]) == {"action", "reasoning",
                                                 "added_delay_min"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_claude_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.agent.claude_agent'`.

- [ ] **Step 3: Implement the builder + schema**

Create `fleet/agent/claude_agent.py`:
```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_claude_agent.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```
git add fleet/agent/claude_agent.py tests/test_claude_agent.py
git commit -m "feat(agent): Claude decision prompt builder + structured-output schema

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Pure `parse_decision`

**Files:**
- Modify: `fleet/agent/claude_agent.py`
- Test: `tests/test_claude_agent.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_claude_agent.py`:
```python
from fleet.agent.claude_agent import parse_decision
from fleet.contracts.state import DecisionEngine


def test_parse_decision_maps_fields():
    d = parse_decision(
        {"action": "reroute", "reasoning": "avoid the flooded edge",
         "added_delay_min": 8},
        event=_event(), seq=1, clock=datetime(2026, 6, 4, 7, 5),
    )
    assert d.id == "DEC_001"
    assert d.event_id == "EVT_001"
    assert d.action == DecisionAction.REROUTE
    assert d.engine == DecisionEngine.CLAUDE
    assert d.reasoning == "avoid the flooded edge"
    assert d.impact_estimate["added_delay_min"] == 8.0
    assert d.timestamp == datetime(2026, 6, 4, 7, 5)


def test_parse_decision_rejects_unknown_action():
    import pytest
    with pytest.raises(ValueError):
        parse_decision(
            {"action": "teleport", "reasoning": "x", "added_delay_min": 1},
            event=_event(), seq=2, clock=datetime(2026, 6, 4, 7, 5),
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_claude_agent.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_decision'`.

- [ ] **Step 3: Implement the parser**

Append to `fleet/agent/claude_agent.py`:
```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_claude_agent.py -v`
Expected: PASS (Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```
git add fleet/agent/claude_agent.py tests/test_claude_agent.py
git commit -m "feat(agent): parse Claude JSON -> Decision

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `ClaudeAgent.decide` with injected transport + per-event fallback

**Files:**
- Modify: `fleet/agent/claude_agent.py`
- Test: `tests/test_claude_agent.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_claude_agent.py`:
```python
from fleet.agent.claude_agent import ClaudeAgent


def test_decide_uses_transport_and_returns_decisions():
    state = build_sample_state()
    calls = []

    def fake_complete(system, user):
        calls.append((system, user))
        return {"action": "reroute", "reasoning": "flood detour",
                "added_delay_min": 12}

    agent = ClaudeAgent(settings=None, complete=fake_complete)
    decisions = agent.decide(state, [_event()])

    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == DecisionAction.REROUTE
    assert d.engine == DecisionEngine.CLAUDE
    assert d.reasoning == "flood detour"
    assert calls and "DEPOT->C001" in calls[0][1]


def test_decide_falls_back_to_rule_action_on_transport_error():
    state = build_sample_state()

    def boom(system, user):
        raise RuntimeError("api down")

    agent = ClaudeAgent(settings=None, complete=boom)
    decisions = agent.decide(state, [_event()])

    assert len(decisions) == 1
    d = decisions[0]
    # FLOODED_AREA -> REROUTE per the rule-based map; tagged as the fallback engine
    assert d.action == DecisionAction.REROUTE
    assert d.engine == DecisionEngine.RULE_BASED
    assert d.event_id == "EVT_001"


def test_decide_no_events_returns_empty():
    agent = ClaudeAgent(settings=None, complete=lambda s, u: {})
    assert agent.decide(build_sample_state(), []) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_claude_agent.py -v`
Expected: FAIL — `ImportError: cannot import name 'ClaudeAgent'`.

- [ ] **Step 3: Implement the agent class**

Append to `fleet/agent/claude_agent.py`:
```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_claude_agent.py -v`
Expected: PASS (all agent tests).

- [ ] **Step 5: Commit**

```
git add fleet/agent/claude_agent.py tests/test_claude_agent.py
git commit -m "feat(agent): ClaudeAgent.decide with injected transport + fallback

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Factory selection + document optional dependency

**Files:**
- Modify: `fleet/factory.py`
- Modify: `requirements.txt`
- Test: `tests/test_factory.py` (append)

- [ ] **Step 1: Write the failing test**

`tests/test_factory.py` already exists (it has `test_cpu_and_rule_are_the_defaults` covering the rule default — do NOT duplicate it). Add the import for `ClaudeAgent` to the existing import block:
```python
from fleet.agent.claude_agent import ClaudeAgent
```
and append these two new tests:
```python
def test_claude_engine_with_key_selects_claude_agent():
    s = load_settings(env={"DECISION_ENGINE": "claude",
                           "ANTHROPIC_API_KEY": "sk-test"})
    comps = build_components(s)
    assert isinstance(comps.decision_engine, ClaudeAgent)


def test_claude_engine_without_key_falls_back_to_rule():
    s = load_settings(env={"DECISION_ENGINE": "claude",
                           "ANTHROPIC_API_KEY": ""})
    comps = build_components(s)
    assert isinstance(comps.decision_engine, RuleBasedEngine)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_factory.py -v`
Expected: FAIL — `test_claude_engine_with_key_selects_claude_agent` fails (factory still returns `RuleBasedEngine` for `claude`).

- [ ] **Step 3: Wire the factory**

In `fleet/factory.py`, add the import:
```python
from fleet.agent.claude_agent import ClaudeAgent
```
Replace the decision-engine block:
```python
    # Decision engine. Claude (LLM) when requested AND an API key is configured;
    # otherwise fall back to the rule-based engine so the system always runs.
    if settings.decision_engine == "claude" and getattr(
            settings, "anthropic_api_key", ""):
        decision_engine: DecisionEngine = ClaudeAgent(settings)
    else:
        decision_engine = RuleBasedEngine()
```
> Note: `DecisionEngine` here is the **interface** already imported at the top of `fleet/factory.py` from `fleet.contracts.interfaces` (the type annotation). It is distinct from the `DecisionEngine` *enum* in `fleet.contracts.state` — do not add a second import; the annotation is only a hint and may be omitted if it causes confusion.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_factory.py -v`
Expected: PASS (new tests).

- [ ] **Step 5: Document the optional dependency**

In `requirements.txt`, append (a comment — do NOT hard-require it, since it needs an API key):
```
# Optional (M5, LLM): official Anthropic SDK. Only needed when
# DECISION_ENGINE=claude with ANTHROPIC_API_KEY set. The rule-based engine is the
# default and the test suite never imports this (transport is injected).
# anthropic
```

- [ ] **Step 6: Full suite + smoke run**

Run: `pytest -v` (expect all green — prior count plus the new claude-agent/factory tests).
Run: `python -m fleet.loop` (still uses the rule-based engine by default; should run clean).

- [ ] **Step 7: Commit**

```
git add fleet/factory.py tests/test_factory.py requirements.txt
git commit -m "feat(factory): select ClaudeAgent for DECISION_ENGINE=claude (rule fallback)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification checklist (end of plan)

- [ ] `pytest -v` fully green.
- [ ] `build_messages` returns a system prompt framing the dispatch role and a user prompt carrying the event's type/target/severity; `_DECISION_SCHEMA` enumerates all 7 `DecisionAction` values and is strict (`additionalProperties: false`, all keys required).
- [ ] `parse_decision` maps `action`/`reasoning`/`added_delay_min` correctly, tags `engine=CLAUDE`, and raises `ValueError` on an unknown action.
- [ ] `ClaudeAgent.decide` round-trips through an injected transport (one call per event) and falls back to the rule-based action (tagged `engine=RULE_BASED`) when the transport raises.
- [ ] Factory returns `ClaudeAgent` only when `DECISION_ENGINE=claude` **and** `ANTHROPIC_API_KEY` is set; otherwise `RuleBasedEngine`.
- [ ] Test suite never imports `anthropic`; it is documented as optional in `requirements.txt`.
- [ ] Only the files named in each task were committed (no `Guide.md`/`problem.txt`/`docs/PROBLEM_STATEMENT.md`).

**Completes M5.** Next milestone: **M6 — real `EwmaForecaster` + `ZScoreDetector`** (demand forecasting + statistical anomaly detection behind the `Forecaster`/`Detector` interfaces, selected by `config/settings.py`).
