# Sovereign Brain v2 — M-C Serve + Integrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the decision engine on a self-hosted NVIDIA NIM — a new `NimAgent` behind the existing `DecisionEngine` interface, selected by config, with the unbreakable fallback chain (NIM → rule-based).

**Architecture:** `NimAgent` reuses the pure `build_messages` / `parse_decision` from `claude_agent` — only the transport differs, and it is **injected** (built lazily from `settings.nim_endpoint` via the OpenAI-compatible client) so the test suite never imports `openai` or hits the network, exactly like `ClaudeAgent`/`CuOptAdapter`. `parse_decision` gains an `engine` parameter so the same parser stamps `LOCAL_NIM` for NIM and keeps `CLAUDE` by default. The factory selects `NimAgent` only when `decision_engine == "nim"` AND an endpoint is set; otherwise the existing Claude/scoring/rule logic is untouched. This milestone is independent of M-A/M-B — it only needs the base NIM image (already pulled).

**Tech Stack:** Python, the OpenAI-compatible NIM endpoint (offline only — transport injected), existing `build_messages`/`parse_decision`/`_ACTION_BY_EVENT`, pytest.

---

### Task 1: `DecisionEngine.LOCAL_NIM` enum value

**Files:**
- Modify: `fleet/contracts/state.py:49-52` (the `DecisionEngine` enum)
- Test: `tests/test_state_schema.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_state_schema.py`:

```python
def test_decision_engine_has_local_nim():
    from fleet.contracts.state import DecisionEngine
    assert DecisionEngine.LOCAL_NIM.value == "local_nim"
    # serialization registry already covers DecisionEngine -> round-trips
    assert DecisionEngine("local_nim") is DecisionEngine.LOCAL_NIM
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state_schema.py::test_decision_engine_has_local_nim -v`
Expected: FAIL with `AttributeError: LOCAL_NIM` (or `ValueError: 'local_nim' is not a valid DecisionEngine`)

- [ ] **Step 3: Write minimal implementation**

In `fleet/contracts/state.py`, add the value to the `DecisionEngine` enum:

```python
class DecisionEngine(str, Enum):
    RULE_BASED = "rule_based"
    CLAUDE = "claude"
    HUMAN = "human"
    LOCAL_NIM = "local_nim"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_state_schema.py::test_decision_engine_has_local_nim -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/contracts/state.py tests/test_state_schema.py
git commit -m "feat(agent): DecisionEngine.LOCAL_NIM enum value"
```

---

### Task 2: Parameterize `parse_decision` with `engine`

**Files:**
- Modify: `fleet/agent/claude_agent.py:72-83`
- Test: `tests/test_claude_agent.py`

The default keeps `CLAUDE`, so the existing `ClaudeAgent` path is byte-identical (`[claude]` description unchanged); `NimAgent` will pass `LOCAL_NIM`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_claude_agent.py`:

```python
def test_parse_decision_stamps_engine():
    from fleet.contracts.state import DecisionEngine, Event, EventType, EventSeverity
    from fleet.agent.claude_agent import parse_decision
    from fleet.scenarios import build_sample_state

    clock = build_sample_state().clock
    evt = Event(id="E1", event_type=EventType.TRAFFIC, target="e1",
                severity=EventSeverity.MEDIUM, started_at=clock)
    data = {"action": "reroute", "reasoning": "x", "added_delay_min": 3}

    d_default = parse_decision(data, evt, 1, clock)
    assert d_default.engine == DecisionEngine.CLAUDE
    assert d_default.description.startswith("[claude]")   # unchanged default

    d_nim = parse_decision(data, evt, 1, clock, engine=DecisionEngine.LOCAL_NIM)
    assert d_nim.engine == DecisionEngine.LOCAL_NIM
    assert d_nim.description.startswith("[local_nim]")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_claude_agent.py::test_parse_decision_stamps_engine -v`
Expected: FAIL with `TypeError: parse_decision() got an unexpected keyword argument 'engine'`

- [ ] **Step 3: Write minimal implementation**

Replace the `parse_decision` function in `fleet/agent/claude_agent.py` with:

```python
def parse_decision(data: dict, event: Event, seq: int, clock,
                   engine: DecisionEngine = DecisionEngine.CLAUDE) -> Decision:
    """Map one model JSON object to a Decision. `engine` stamps the source
    (default CLAUDE; NimAgent passes LOCAL_NIM). Raises ValueError if `action`
    is not a valid DecisionAction value (caller decides how to recover)."""
    action = DecisionAction(data["action"])   # raises ValueError on unknown
    added_delay = float(data.get("added_delay_min", _DEFAULT_ADDED_DELAY_MIN))
    return Decision(
        id=f"DEC_{seq:03d}", timestamp=clock, event_id=event.id,
        action=action, engine=engine,
        description=f"[{engine.value}] respond to {event.event_type.value} on {event.target}",
        impact_estimate={"added_delay_min": added_delay},
        reasoning=str(data.get("reasoning", "")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_claude_agent.py -v`
Expected: PASS (existing claude tests still green — default engine keeps `[claude]`; plus the new test)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/claude_agent.py tests/test_claude_agent.py
git commit -m "feat(agent): parse_decision stamps engine (default CLAUDE; NIM passes LOCAL_NIM)"
```

---

### Task 3: NIM settings

**Files:**
- Modify: `config/settings.py` (two fields after `oracle_min_gap`; two lines in `load_settings`)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_nim_settings_defaults_and_override():
    from config.settings import load_settings
    s = load_settings({})
    assert s.nim_endpoint == ""
    assert s.nim_model == "nvidia/llama-3.1-nemotron-nano-8b-v1"
    s2 = load_settings({"NIM_ENDPOINT": "http://localhost:8000/v1", "NIM_MODEL": "x"})
    assert s2.nim_endpoint == "http://localhost:8000/v1"
    assert s2.nim_model == "x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_nim_settings_defaults_and_override -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'nim_endpoint'`

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add two fields right after the `oracle_min_gap` line:

```python
    nim_endpoint: str = ""                # M-C(SBv2): OpenAI-compatible NIM endpoint (empty -> NimAgent disabled)
    nim_model: str = "nvidia/llama-3.1-nemotron-nano-8b-v1"  # M-C(SBv2): served NIM model id
```

In `load_settings`, add two lines right after the `oracle_min_gap=...` line:

```python
        nim_endpoint=e.get("NIM_ENDPOINT", ""),
        nim_model=e.get("NIM_MODEL", "nvidia/llama-3.1-nemotron-nano-8b-v1"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py::test_nim_settings_defaults_and_override -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_config.py
git commit -m "feat(agent): NIM settings (nim_endpoint, nim_model)"
```

---

### Task 4: `NimAgent` (decide + rule fallback + lazy transport guard)

**Files:**
- Create: `fleet/agent/nim_agent.py`
- Test: `tests/test_nim_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_nim_agent.py`:

```python
import pytest

from config.settings import load_settings
from fleet.contracts.state import (
    DecisionEngine, DecisionAction, Event, EventType, EventSeverity,
)
from fleet.scenarios import build_sample_state


def _event(event_type, target, severity, clock):
    return Event(id="E1", event_type=event_type, target=target,
                 severity=severity, started_at=clock)


def test_nim_agent_decide_parses_and_tags_local_nim():
    from fleet.agent.nim_agent import NimAgent
    state = build_sample_state()
    evt = _event(EventType.TRAFFIC, "e1", EventSeverity.MEDIUM, state.clock)

    def fake_complete(system, user):
        return {"action": "reroute", "reasoning": "avoid congestion",
                "added_delay_min": 8}

    [d] = NimAgent(settings=None, complete=fake_complete).decide(state, [evt])
    assert d.action == DecisionAction.REROUTE
    assert d.engine == DecisionEngine.LOCAL_NIM
    assert d.reasoning == "avoid congestion"
    assert d.impact_estimate["added_delay_min"] == 8.0


def test_nim_agent_falls_back_to_rule_on_transport_error():
    from fleet.agent.nim_agent import NimAgent
    state = build_sample_state()
    evt = _event(EventType.VEHICLE_BREAKDOWN, "V001", EventSeverity.CRITICAL, state.clock)

    def boom(system, user):
        raise RuntimeError("endpoint down")

    [d] = NimAgent(settings=None, complete=boom).decide(state, [evt])
    assert d.engine == DecisionEngine.RULE_BASED              # demo never hard-fails
    assert d.action == DecisionAction.REALLOCATE             # rule map for breakdown


def test_nim_agent_build_default_complete_requires_endpoint():
    from fleet.agent.nim_agent import NimAgent
    agent = NimAgent(settings=load_settings({}))             # no endpoint, no transport
    with pytest.raises(RuntimeError, match="nim_endpoint is empty"):
        agent._build_default_complete()                      # raises before importing openai
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nim_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.agent.nim_agent'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/agent/nim_agent.py`:

```python
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
        from openai import OpenAI  # optional dep

        client = OpenAI(base_url=endpoint, api_key="not-needed")
        model = getattr(self.settings, "nim_model", "") or ""

        def complete(system: str, user: str) -> dict:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=0.0,
                extra_body={"nvext": {"guided_json": _DECISION_SCHEMA}},
            )
            return json.loads(resp.choices[0].message.content)

        return complete
```

> Note for the executor: the `extra_body={"nvext": {"guided_json": ...}}` form is the NIM guided-decoding convention; if the deployed NIM build expects `response_format={"type": "json_schema", ...}` instead, adjust only inside `_build_default_complete` (the suite never executes it, so no test changes). The fine-tune (M-D) plus this guided-JSON guard both push output toward valid `_DECISION_SCHEMA`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nim_agent.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/nim_agent.py tests/test_nim_agent.py
git commit -m "feat(agent): NimAgent — DecisionEngine over NIM, injected transport + rule fallback"
```

---

### Task 5: Factory selects `NimAgent`

**Files:**
- Modify: `fleet/factory.py:20-22` (import) and `fleet/factory.py:48-54` (selection)
- Test: `tests/test_factory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_factory.py`:

```python
def test_factory_selects_nim_agent_when_endpoint_set():
    from fleet.factory import build_components
    from fleet.agent.nim_agent import NimAgent
    from config.settings import load_settings
    s = load_settings({"DECISION_ENGINE": "nim",
                       "NIM_ENDPOINT": "http://localhost:8000/v1"})
    assert isinstance(build_components(s).decision_engine, NimAgent)


def test_factory_nim_without_endpoint_falls_back_to_rule():
    from fleet.factory import build_components
    from fleet.agent.rule_based import RuleBasedEngine
    from config.settings import load_settings
    s = load_settings({"DECISION_ENGINE": "nim"})   # engine requested, no endpoint
    assert isinstance(build_components(s).decision_engine, RuleBasedEngine)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_factory.py::test_factory_selects_nim_agent_when_endpoint_set -v`
Expected: FAIL with `AssertionError` (currently returns `RuleBasedEngine`)

- [ ] **Step 3: Write minimal implementation**

In `fleet/factory.py`, add the import next to the other agent imports (after the `ClaudeAgent` import):

```python
from fleet.agent.nim_agent import NimAgent
```

Replace the decision-engine selection block with (adds the `nim` branch first, keeps the rest unchanged):

```python
    # Decision engine. NIM (self-hosted LLM) when requested AND an endpoint is
    # set; Claude (LLM) when requested AND an API key is configured; the scoring
    # policy when requested; otherwise the rule-based engine so the system always
    # runs.
    if settings.decision_engine == "nim" and getattr(settings, "nim_endpoint", ""):
        decision_engine: DecisionEngine = NimAgent(settings)
    elif settings.decision_engine == "claude" and getattr(
            settings, "anthropic_api_key", ""):
        decision_engine = ClaudeAgent(settings)
    elif settings.decision_engine == "scoring":
        decision_engine = ScoringEngine(settings)
    else:
        decision_engine = RuleBasedEngine()
```

(Constructing `NimAgent(settings)` does **not** build the transport or import `openai` — that is lazy — so this import and selection stay network-free.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_factory.py -v`
Expected: PASS (the two new tests, plus the existing factory tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add fleet/factory.py tests/test_factory.py
git commit -m "feat(agent): factory selects NimAgent on DECISION_ENGINE=nim + endpoint"
```

---

### Task 6: Regression + loop smoke (+ optional live NIM serve)

**Files:**
- No code changes — verifies the milestone is purely additive (default path and the loop untouched; suite stays network/GPU-free).

- [ ] **Step 1: Run the whole suite**

Run: `pytest -q`
Expected: PASS — the prior count plus the new tests (1 in `test_state_schema.py`, 1 in `test_claude_agent.py`, 1 in `test_config.py`, 3 in `test_nim_agent.py`, 2 in `test_factory.py`). No previously-passing test changes status; `openai` is never imported (transport injected/lazy).

- [ ] **Step 2: Smoke the headless loop (default path unchanged)**

Run: `python -m fleet.loop`
Expected: clean run, no traceback. Default `decision_engine="rule"`, so `NimAgent` is constructed only when `DECISION_ENGINE=nim` + `NIM_ENDPOINT` are set; the loop output is unchanged from before this milestone.

- [ ] **Step 3 (OPTIONAL — needs the H200 + pulled NIM image; do only if serving now):** Live end-to-end on the self-hosted base NIM

Serve the base NIM (image already pulled), then point the loop at it:

```bash
# serve (background); cache under /raid/nim-cache, expose OpenAI-compatible API on :8000
docker run -d --gpus '"device=0,1"' --shm-size=16g \
  -e NGC_API_KEY="$NGC_API_KEY" -v /raid/nim-cache:/opt/nim/.cache -p 8000:8000 \
  nvcr.io/nim/nvidia/llama-3.1-nemotron-nano-8b-v1:latest

# once `curl http://localhost:8000/v1/models` lists the model, run the loop on it:
DECISION_ENGINE=nim NIM_ENDPOINT=http://localhost:8000/v1 python -m fleet.loop
```

Expected: the loop runs end-to-end with decisions tagged `engine=local_nim` (no Claude, no API key). If the endpoint is down or returns invalid output, each event falls back to the rule-based action (`engine=rule_based`) and the loop still completes — the unbreakable chain. This step proves the self-hosted story; it is NOT required for the milestone's definition of done (the suite + loop smoke are).

- [ ] **Step 4: Commit (only if an incidental fix was needed; otherwise skip)**

If `pytest -q` and the loop smoke were already green with no edits, there is nothing to commit — this task is a verification gate.

---

## Self-Review

**Spec coverage (vs `2026-06-07-sovereign-brain-v2-oracle-design.md` §4.7–4.9, §5, §10 M-C):**
- §4.7 self-hosted NIM serving (base model, OpenAI-compatible, guided-JSON) → Task 4 default transport + Task 6 Step 3 live serve. ✓
- §4.8 `NimAgent` reuses pure `build_messages`/`parse_decision`, transport injected, `DecisionEngine.LOCAL_NIM`, `parse_decision` parameterized to stamp the engine → Tasks 1, 2, 4. ✓
- §4.9 settings `decision_engine="nim"`, `nim_endpoint`, `nim_model`; factory selects when `nim` AND endpoint set, else existing logic (one-line, mirrors cuOpt) → Tasks 3, 5. ✓
- §5 fallback chain (invalid output / endpoint down → rule-based, tagged `RULE_BASED`) → Task 4 `_fallback` + its test; the base-NIM→fine-tuned-NIM layer is M-D. ✓
- §7 boundary: only `nim_agent.py` + config touch runtime; suite never imports `openai`/network/GPU (transport injected, lazy import; factory construction is transport-free) → Tasks 4–6. ✓
- §10 M-C "base NIM + NimAgent via factory + fallback chain; full loop end-to-end on the self-hosted model" → Task 6 (Steps 1–2 required CPU regression; Step 3 the live GPU smoke). ✓

**Placeholder scan:** No TBD/TODO; every code step is complete; every command has expected output. The one guided-decoding caveat (Task 4 note) is an explicit, bounded adjustment point inside the never-tested transport, not a placeholder.

**Type consistency:** `parse_decision(data, event, seq, clock, engine=DecisionEngine.CLAUDE)` (Task 2) is exactly how `NimAgent.decide` calls it with `engine=DecisionEngine.LOCAL_NIM` (Task 4). `NimAgent(settings=None, complete=None)` mirrors `ClaudeAgent`; `complete(system, user) -> dict` is the injected transport contract used by both the tests and `_get_complete`. The factory `nim` branch (Task 5) constructs `NimAgent(settings)` — same signature. `_ACTION_BY_EVENT` (from `rule_based`) and `_DECISION_SCHEMA` (from `claude_agent`) are imported, not redefined. `DecisionEngine.LOCAL_NIM` (Task 1) is the value stamped in Tasks 2/4 and asserted across the NIM tests.

**Independence:** This milestone does not import `fleet/agent/oracle.py` or `fleet/agent/dataset.py` — it can be executed before, after, or in parallel with M-A/M-B. It needs only the base NIM image for the optional live smoke; the required DoD is CPU-only.
