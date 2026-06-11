# M-D: Scoring-Policy Decision Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the naive 1-to-1 event→action map with a context-aware **scoring policy**: for each event, enumerate candidate actions, score each by a cost function (SLA-breach risk, added delay, priority-weighted dropped orders), pick the cheapest, and emit **structured reasoning** (the scored table). Add modest **proactive** decisions (gated). This becomes a credible deterministic baseline — a better teacher/fallback for the Sovereign Brain and richer explainable cards for the demo — at $0, CPU, no new dependency.

**Architecture:** New `fleet/agent/scoring_engine.py` with pure module-level functions (`candidate_actions`, `score_action`, scoring tables) and a `ScoringEngine` class implementing the `DecisionEngine` protocol (`decide(state, events) -> List[Decision]`). The existing `RuleBasedEngine` and its `_ACTION_BY_EVENT` map are **untouched** (ClaudeAgent's fallback and the Sovereign-Brain teacher both depend on them). The engine is selected by `DECISION_ENGINE=scoring`; `rule` stays the default. The scored alternatives are persisted in `Decision.impact_estimate` (a `Dict[str, float]`: `score_<action>` per candidate + `added_delay_min`) and summarized in `Decision.reasoning`. Proactive shortfall decisions are behind an `enable_proactive` flag (default False) so the approval gate / loop are unaffected by default.

**Tech Stack:** Python stdlib only. pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-06-07-core-modules-deepening-design.md` §6.1 (scoring policy), §6.2 (proactive), §6.3 (structured reasoning). Counterfactual lookahead (§6 "Cách C") is explicit stretch — NOT in this plan.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `config/settings.py` | `decision_engine` value `scoring`; `score_w_sla/delay/drop`; `enable_proactive` | add 4 fields + env parsing |
| `fleet/agent/scoring_engine.py` | scoring tables, `candidate_actions`, `score_action`, `ScoringEngine` | create |
| `fleet/factory.py` | select `ScoringEngine` on `DECISION_ENGINE=scoring` | modify |
| `tests/test_scoring_engine.py` | unit tests: candidates, scoring, decide, reasoning, proactive | create |
| `tests/test_config.py`, `tests/test_factory.py` | new settings + factory selection | modify |

**Preserve:** `fleet/agent/rule_based.py` (incl. `_ACTION_BY_EVENT`) is untouched; `RuleBasedEngine` stays the default and the Claude fallback. `Decision`/`DecisionAction`/`DecisionEngine` schema unchanged (we tag scoring decisions `DecisionEngine.RULE_BASED` to avoid an enum/serialization change; a dedicated `SCORING` enum value is a trivial follow-on if the demo wants a distinct badge).

---

## Task 1: Scoring settings

**Files:**
- Modify: `config/settings.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_scoring_defaults():
    s = load_settings(env={})
    assert s.score_w_sla == 50.0
    assert s.score_w_delay == 1.0
    assert s.score_w_drop == 50.0
    assert s.enable_proactive is False


def test_scoring_env_override():
    s = load_settings(env={"DECISION_ENGINE": "scoring", "ENABLE_PROACTIVE": "1"})
    assert s.decision_engine == "scoring"
    assert s.enable_proactive is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_scoring_defaults -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'score_w_sla'`

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add to `Settings` (after the M-C detector fields):

```python
    score_w_sla: float = 50.0             # M-D: weight on SLA-breach risk (unresolved disruption)
    score_w_delay: float = 1.0            # M-D: weight on added delay minutes
    score_w_drop: float = 50.0            # M-D: weight on priority-weighted dropped orders
    enable_proactive: bool = False        # M-D: emit proactive shortfall decisions
```

In `load_settings`, add:

```python
        score_w_sla=float(e.get("SCORE_W_SLA", "50.0")),
        score_w_delay=float(e.get("SCORE_W_DELAY", "1.0")),
        score_w_drop=float(e.get("SCORE_W_DROP", "50.0")),
        enable_proactive=e.get("ENABLE_PROACTIVE", "0") in ("1", "true", "True"),
```

(`decision_engine` already exists; `scoring` is a new allowed value.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_config.py
git commit -m "feat(agent): scoring-policy settings (weights + proactive gate)"
```

---

## Task 2: Candidate actions + scoring tables

**Files:**
- Create: `fleet/agent/scoring_engine.py`
- Test: `tests/test_scoring_engine.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_scoring_engine.py`:

```python
from fleet.contracts.state import EventType, DecisionAction
from fleet.agent.scoring_engine import candidate_actions, _resolves


def test_candidates_per_event_type():
    assert DecisionAction.REROUTE in candidate_actions(EventType.FLOODED_AREA)
    assert DecisionAction.REALLOCATE in candidate_actions(EventType.VEHICLE_BREAKDOWN)
    assert len(candidate_actions(EventType.INVENTORY_SHORTAGE)) >= 2


def test_resolves_table():
    assert _resolves(EventType.FLOODED_AREA, DecisionAction.REROUTE) is True
    assert _resolves(EventType.FLOODED_AREA, DecisionAction.DEFER) is False
    assert _resolves(EventType.INVENTORY_SHORTAGE, DecisionAction.CANCEL) is True
    assert _resolves(EventType.INVENTORY_SHORTAGE, DecisionAction.REPRIORITIZE) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring_engine.py::test_candidates_per_event_type -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.agent.scoring_engine'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/agent/scoring_engine.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/scoring_engine.py tests/test_scoring_engine.py
git commit -m "feat(agent): scoring candidate actions + resolves tables"
```

---

## Task 3: Context cost function

**Files:**
- Modify: `fleet/agent/scoring_engine.py` (`_priority_weight`, `_Weights`, `score_action`)
- Test: `tests/test_scoring_engine.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scoring_engine.py`:

```python
from datetime import datetime

from fleet.contracts.state import Event, EventSeverity
from fleet.agent.scoring_engine import score_action, _Weights
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def _evt(etype, target, sev=EventSeverity.HIGH):
    return Event(id="E1", event_type=etype, target=target, severity=sev,
                 started_at=datetime(2026, 6, 7, 8, 0))


def test_resolving_action_cheaper_than_nonresolving():
    s = build_sample_state()
    w = _Weights(load_settings())
    e = _evt(EventType.FLOODED_AREA, "DEPOT->C001#2", EventSeverity.CRITICAL)
    reroute = score_action(s, e, DecisionAction.REROUTE, w)     # resolves
    defer = score_action(s, e, DecisionAction.DEFER, w)         # does not resolve
    assert reroute < defer


def test_lower_delay_resolving_action_preferred():
    s = build_sample_state()
    w = _Weights(load_settings())
    e = _evt(EventType.FLOODED_AREA, "DEPOT->C001#2")
    assert (score_action(s, e, DecisionAction.REROUTE, w)
            < score_action(s, e, DecisionAction.RESCHEDULE, w))


def test_priority_weight_scales_drop_cost():
    s = build_sample_state()
    w = _Weights(load_settings())
    # C001 has priority 1 (urgent); compare CANCEL cost for an urgent vs a fabricated low-prio customer
    s.customers["C001"].priority = 1
    s.customers["C002"].priority = 4
    e_urgent = _evt(EventType.INVENTORY_SHORTAGE, "C001")
    e_low = _evt(EventType.INVENTORY_SHORTAGE, "C002")
    assert (score_action(s, e_urgent, DecisionAction.CANCEL, w)
            > score_action(s, e_low, DecisionAction.CANCEL, w))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring_engine.py::test_resolving_action_cheaper_than_nonresolving -v`
Expected: FAIL — `ImportError: cannot import name 'score_action'`

- [ ] **Step 3: Write minimal implementation**

Append to `fleet/agent/scoring_engine.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring_engine.py -v`
Expected: PASS (resolving cheaper, lower-delay preferred, priority scales drop cost)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/scoring_engine.py tests/test_scoring_engine.py
git commit -m "feat(agent): context cost function (SLA/delay/priority-weighted drops)"
```

---

## Task 4: ScoringEngine.decide with structured reasoning

**Files:**
- Modify: `fleet/agent/scoring_engine.py` (`ScoringEngine`)
- Test: `tests/test_scoring_engine.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scoring_engine.py`:

```python
from fleet.contracts.state import DecisionEngine
from fleet.contracts.interfaces import DecisionEngine as DecisionEngineProto
from fleet.agent.scoring_engine import ScoringEngine


def test_scoring_engine_conforms_to_protocol():
    assert isinstance(ScoringEngine(load_settings()), DecisionEngineProto)


def test_decide_picks_lowest_cost_and_records_table():
    s = build_sample_state()
    eng = ScoringEngine(load_settings())
    e = _evt(EventType.FLOODED_AREA, "DEPOT->C001#2", EventSeverity.CRITICAL)
    decisions = eng.decide(s, [e])
    assert len(decisions) == 1
    d = decisions[0]
    assert d.action == DecisionAction.REROUTE              # cheapest resolving action
    assert d.event_id == "E1"
    assert "score_reroute" in d.impact_estimate            # scored table persisted
    assert "score_defer" in d.impact_estimate
    assert d.impact_estimate["added_delay_min"] == 8.0
    assert "reroute" in d.reasoning and "defer" in d.reasoning   # alternatives in prose


def test_decide_is_deterministic():
    s = build_sample_state()
    e = _evt(EventType.VEHICLE_BREAKDOWN, "V001", EventSeverity.CRITICAL)
    a = ScoringEngine(load_settings()).decide(s, [e])[0]
    b = ScoringEngine(load_settings()).decide(s, [e])[0]
    assert a.action == b.action and a.impact_estimate == b.impact_estimate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring_engine.py::test_decide_picks_lowest_cost_and_records_table -v`
Expected: FAIL — `ImportError: cannot import name 'ScoringEngine'`

- [ ] **Step 3: Write minimal implementation**

Append to `fleet/agent/scoring_engine.py`:

```python
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
        return []        # filled in Task 5
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring_engine.py -v`
Expected: PASS (protocol, picks best + table, deterministic)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/scoring_engine.py tests/test_scoring_engine.py
git commit -m "feat(agent): ScoringEngine.decide with structured reasoning table"
```

---

## Task 5: Proactive shortfall decisions (gated)

**Files:**
- Modify: `fleet/agent/scoring_engine.py` (`_proactive`)
- Test: `tests/test_scoring_engine.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scoring_engine.py`:

```python
def test_proactive_off_by_default():
    s = build_sample_state()
    eng = ScoringEngine(load_settings())          # enable_proactive False
    # drive depot stock to zero so everything is "at risk"
    s.depot.inventory = {sku: 0 for sku in s.depot.inventory}
    assert eng.decide(s, []) == []                # no events, proactive disabled => nothing


def test_proactive_emits_once_per_at_risk_customer_when_enabled():
    s = build_sample_state()
    eng = ScoringEngine(load_settings(env={"ENABLE_PROACTIVE": "1"}))
    # make SKU001 short: zero its stock (C001 & C002 order SKU001)
    s.depot.inventory["SKU001"] = 0
    first = eng.decide(s, [])
    ids = {d.id for d in first}
    assert "DEC_PROACTIVE_C001" in ids
    assert all(d.event_id is None for d in first)
    assert all(d.action == DecisionAction.REPRIORITIZE for d in first)
    # second call with the same shortfall must NOT re-emit (dedup)
    second = eng.decide(s, [])
    assert "DEC_PROACTIVE_C001" not in {d.id for d in second}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring_engine.py::test_proactive_emits_once_per_at_risk_customer_when_enabled -v`
Expected: FAIL — `_proactive` returns `[]`, so `DEC_PROACTIVE_C001` is never emitted.

- [ ] **Step 3: Write minimal implementation**

Replace the `_proactive` stub in `fleet/agent/scoring_engine.py` with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring_engine.py -v`
Expected: PASS (off by default; emits once per at-risk customer when enabled; dedups)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/scoring_engine.py tests/test_scoring_engine.py
git commit -m "feat(agent): gated proactive shortfall decisions (state projection)"
```

---

## Task 6: Factory wiring (`DECISION_ENGINE=scoring`)

**Files:**
- Modify: `fleet/factory.py`
- Test: `tests/test_factory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_factory.py`:

```python
def test_factory_selects_scoring_engine():
    from fleet.agent.scoring_engine import ScoringEngine
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={"DECISION_ENGINE": "scoring"}))
    assert isinstance(c.decision_engine, ScoringEngine)


def test_factory_defaults_to_rule_engine():
    from fleet.agent.rule_based import RuleBasedEngine
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={}))
    assert isinstance(c.decision_engine, RuleBasedEngine)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_factory.py::test_factory_selects_scoring_engine -v`
Expected: FAIL — the factory never returns a `ScoringEngine`.

- [ ] **Step 3: Write minimal implementation**

In `fleet/factory.py`:

(a) Add an import near `from fleet.agent.rule_based import RuleBasedEngine`:

```python
from fleet.agent.scoring_engine import ScoringEngine
```

(b) Replace the decision-engine selection block with:

```python
    # Decision engine. Claude (LLM) when requested AND an API key is configured;
    # the scoring policy when requested; otherwise the rule-based engine so the
    # system always runs.
    if settings.decision_engine == "claude" and getattr(
            settings, "anthropic_api_key", ""):
        decision_engine: DecisionEngine = ClaudeAgent(settings)
    elif settings.decision_engine == "scoring":
        decision_engine = ScoringEngine(settings)
    else:
        decision_engine = RuleBasedEngine()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_factory.py -v`
Expected: PASS (scoring selected on request; rule default unchanged)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS — `DECISION_ENGINE=rule` default unchanged; new scoring tests green.

- [ ] **Step 6: Headless smoke with the scoring engine + layered detector + weather**

Run (PowerShell): `$env:DECISION_ENGINE="scoring"; $env:DETECTOR_ENGINE="layered"; $env:ENABLE_WEATHER="1"; python -m fleet.loop; Remove-Item Env:\DECISION_ENGINE; Remove-Item Env:\DETECTOR_ENGINE; Remove-Item Env:\ENABLE_WEATHER`
Expected: runs clean; decisions carry `[scoring]` descriptions + a scored-alternatives `reasoning`; no traceback.

- [ ] **Step 7: Commit**

```bash
git add fleet/factory.py tests/test_factory.py
git commit -m "feat(agent): factory selects ScoringEngine on DECISION_ENGINE=scoring"
```

---

## Self-Review

**Spec coverage (§6):** scoring policy with candidate enumeration + context cost (Tasks 2–4, §6.1); structured reasoning persisted in `impact_estimate` + prose (Task 4, §6.3); proactive shortfall decisions, gated (Task 5, §6.2 — state-projection version; the forecaster-driven pre-order is a noted follow-on); factory selection with `rule` default + Claude path preserved (Task 6). Counterfactual lookahead is spec-marked stretch — out of scope.

**Placeholder scan:** the `_proactive` `return []` stub in Task 4 is intentional TDD (replaced in Task 5), not a leftover. Every other step has concrete code/commands.

**Type consistency:** `ScoringEngine.decide(state, events) -> List[Decision]` matches the `DecisionEngine` protocol (`interfaces.py`). `candidate_actions(event_type) -> List[DecisionAction]`, `score_action(state, event, action, weights) -> float`, `_Weights(settings)`, `_priority_weight(state, event)` — defined in Tasks 2–3 and used unchanged in Tasks 4–5. `Decision` fields (`id/timestamp/event_id/action/engine/description/impact_estimate/reasoning`) match `state.py:233-246`. All 7 `DecisionAction` values and `DecisionEngine.RULE_BASED` confirmed against `state.py:49-62`.

**Determinism:** no RNG; `decide` sorts by `(cost, action.value)` for a stable tie-break; proactive iterates `sorted(state.customers)`. Default `DECISION_ENGINE=rule` ⇒ zero behavior change ⇒ same pytest count.

**Safety:** `rule_based.py` / `_ACTION_BY_EVENT` untouched (Claude fallback + Sovereign-Brain teacher intact); proactive gated off by default (approval gate / loop unaffected); scoring decisions tagged `RULE_BASED` to avoid an enum/serialization change.

---

## Series complete

M-A (demand) → M-A2 (traffic/weather) → M-B (Holt-Winters) → M-C (statistical detectors) → M-D (scoring engine). Named stretch items deferred across the series: simulator cascade + position interpolation (§3.3/§3.4), detector cascade-correlation (§5.4), forecast-driven pre-order + counterfactual lookahead (§6.2/§6 Cách C). Each is independently addable behind the same interfaces.
