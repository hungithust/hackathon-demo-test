# Sovereign Brain v2 — M-B Data Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the M-A oracle into a dataset factory — drive the simulator over seeded scenarios, grade every candidate action by realized outcome, keep only the proven-best label, attach reasoning (Sonnet 4.6 Batch, with a $0 templated fallback), and emit train/test JSONL split by scenario seed.

**Architecture:** A pure, CPU-only module `fleet/agent/dataset.py` holds every testable piece — scenario generation, oracle grading (`grade_example`), the informative-gap filter, templated reasoning, record assembly (train/serve-parity via the shipped `build_messages`), seed-based split, and the Sonnet-Batch orchestrator with an **injected** transport (the suite never imports `anthropic` or hits the network — same discipline as `ClaudeAgent`). A thin `scripts/gen_dataset.py` wires the real optimizer + (optional) Batch transport and writes the files. Depends on M-A (`fleet/agent/oracle.py`) being merged.

**Tech Stack:** Python, the M-A oracle, `dataclasses.replace`, existing `WorldSimulator` / `plan_routes` / `build_messages` / `ScoringEngine`, the Anthropic Message Batches API (offline only), pytest.

---

### Task 1: Informative-gap setting

**Files:**
- Modify: `config/settings.py` (add field after `oracle_horizon_ticks`)
- Modify: `config/settings.py` (add the `load_settings` line)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_oracle_min_gap_default_and_override():
    from config.settings import load_settings
    assert load_settings({}).oracle_min_gap == 1.0
    assert load_settings({"ORACLE_MIN_GAP": "5"}).oracle_min_gap == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_oracle_min_gap_default_and_override -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'oracle_min_gap'`

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add a field right after the `oracle_horizon_ticks` line:

```python
    oracle_min_gap: float = 1.0           # M-B(SBv2): min best/worst realized-cost gap to keep an example (else no signal)
```

In `load_settings`, add this line just after the `oracle_horizon_ticks=...` line:

```python
        oracle_min_gap=float(e.get("ORACLE_MIN_GAP", "1.0")),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py::test_oracle_min_gap_default_and_override -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_config.py
git commit -m "feat(dataset): oracle_min_gap setting (drop uninformative examples)"
```

---

### Task 2: `realized_delay_minutes` + `is_informative`

**Files:**
- Create: `fleet/agent/dataset.py`
- Test: `tests/test_dataset.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dataset.py`:

```python
from datetime import datetime, timedelta

from fleet.contracts.state import (
    WorldState, Depot, Location, CustomerProfile, TimeWindow, Stop, VehicleRoute,
    DecisionAction,
)
from fleet.agent.dataset import realized_delay_minutes, is_informative

_BASE = datetime(2026, 6, 4, 6, 0)


def _depot():
    return Depot(location=Location(0.0, 0.0, "d", "d"), inventory={},
                 opening_time=_BASE, closing_time=_BASE + timedelta(hours=12))


def test_realized_delay_sums_overdue_minutes():
    cust = CustomerProfile(
        id="C1", type="market", location=Location(0.0, 0.0, "c", "c"), orders={},
        time_window=TimeWindow(_BASE, _BASE + timedelta(hours=1)), priority=2)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1, minutes=20))  # 20 min late
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    assert realized_delay_minutes(st) == 20.0


def test_realized_delay_zero_when_on_time():
    cust = CustomerProfile(
        id="C1", type="market", location=Location(0.0, 0.0, "c", "c"), orders={},
        time_window=TimeWindow(_BASE, _BASE + timedelta(hours=2)), priority=2)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1))
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    assert realized_delay_minutes(st) == 0.0


def test_is_informative_uses_cost_gap():
    scored = [(DecisionAction.REPRIORITIZE, 10.0), (DecisionAction.CANCEL, 60.0)]
    assert is_informative(scored, min_gap=1.0) is True
    assert is_informative(scored, min_gap=100.0) is False
    assert is_informative([(DecisionAction.REROUTE, 5.0)], min_gap=1.0) is False
    assert is_informative([], min_gap=1.0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dataset.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.agent.dataset'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/agent/dataset.py`:

```python
"""Dataset factory for Sovereign Brain v2 (M-B). Drives the simulator over seeded
scenarios, grades each candidate action with the M-A oracle, keeps the proven-best
label, attaches reasoning (Sonnet Batch or a $0 templated fallback), and emits
train/serve-parity JSONL. Pure CPU; the Batch transport is injected so the test
suite never imports anthropic or touches the network."""

from fleet.contracts.state import WorldState


def realized_delay_minutes(state: WorldState) -> float:
    """Total minutes that delivered stops arrived past their customer's window."""
    total = 0.0
    for route in state.plan.values():
        for stop in route.stops:
            if stop.actual_arrival is None:
                continue
            cust = state.customers.get(stop.customer_id)
            if cust is None:
                continue
            overdue = (stop.actual_arrival - cust.time_window.end).total_seconds() / 60.0
            if overdue > 0:
                total += overdue
    return total


def is_informative(scored, min_gap: float) -> bool:
    """True when the best/worst realized-cost gap is at least `min_gap` — i.e. the
    candidate actions actually differ, so the example teaches something."""
    if not scored:
        return False
    costs = [c for _, c in scored]
    return (max(costs) - min(costs)) >= min_gap
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dataset.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/dataset.py tests/test_dataset.py
git commit -m "feat(dataset): realized_delay_minutes + is_informative (gap filter)"
```

---

### Task 3: `templated_reasoning` ($0 reasoning)

**Files:**
- Modify: `fleet/agent/dataset.py`
- Test: `tests/test_dataset.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dataset.py`:

```python
def test_templated_reasoning_names_choice_and_alternatives():
    from fleet.contracts.state import Event, EventType, EventSeverity, DecisionAction
    from fleet.agent.dataset import templated_reasoning
    evt = Event(id="E1", event_type=EventType.INVENTORY_SHORTAGE, target="SKU001",
                severity=EventSeverity.HIGH, started_at=_BASE)
    scored = [(DecisionAction.REPRIORITIZE, 12.0),
              (DecisionAction.DEFER, 20.0),
              (DecisionAction.CANCEL, 60.0)]
    text = templated_reasoning(evt, scored)
    assert text == (
        "Simulated each option for the inventory_shortage on SKU001; "
        "chose reprioritize with the lowest realized cost 12.0 "
        "versus defer=20.0, cancel=60.0.")


def test_templated_reasoning_handles_single_candidate():
    from fleet.contracts.state import Event, EventType, EventSeverity, DecisionAction
    from fleet.agent.dataset import templated_reasoning
    evt = Event(id="E2", event_type=EventType.TRAFFIC, target="e1",
                severity=EventSeverity.MEDIUM, started_at=_BASE)
    text = templated_reasoning(evt, [(DecisionAction.REROUTE, 8.0)])
    assert text == (
        "Simulated each option for the traffic on e1; "
        "chose reroute with the lowest realized cost 8.0.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dataset.py::test_templated_reasoning_names_choice_and_alternatives -v`
Expected: FAIL with `ImportError: cannot import name 'templated_reasoning'`

- [ ] **Step 3: Write minimal implementation**

Append to `fleet/agent/dataset.py`:

```python
from fleet.contracts.state import Event


def templated_reasoning(event: Event, scored) -> str:
    """A $0, deterministic justification built from the oracle's scored options."""
    best, best_cost = scored[0]
    base = (f"Simulated each option for the {event.event_type.value} on "
            f"{event.target}; chose {best.value} with the lowest realized cost "
            f"{best_cost:.1f}")
    alts = ", ".join(f"{a.value}={c:.1f}" for a, c in scored[1:])
    return base + (f" versus {alts}." if alts else ".")
```

(Merge the new `Event` import into the existing `from fleet.contracts.state import WorldState` line — make it `from fleet.contracts.state import WorldState, Event`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dataset.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/dataset.py tests/test_dataset.py
git commit -m "feat(dataset): templated_reasoning — deterministic $0 justification"
```

---

### Task 4: `build_record` (train/serve-parity JSONL row)

**Files:**
- Modify: `fleet/agent/dataset.py`
- Test: `tests/test_dataset.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dataset.py`:

```python
def test_build_record_matches_build_messages_and_schema():
    from fleet.contracts.state import Event, EventType, EventSeverity, DecisionAction
    from fleet.agent.claude_agent import build_messages
    from fleet.agent.dataset import build_record
    from fleet.scenarios import build_sample_state

    state = build_sample_state()
    evt = Event(id="E1", event_type=EventType.DEMAND_SURGE, target="C001",
                severity=EventSeverity.MEDIUM, started_at=state.clock)
    record = build_record(state, evt, DecisionAction.REPRIORITIZE, 3.0, "because.")

    system, user = build_messages(state, evt)
    assert record["system"] == system            # train/serve parity
    assert record["user"] == user
    assert record["assistant"] == {
        "action": "reprioritize", "reasoning": "because.", "added_delay_min": 3.0}
    # assistant turn carries exactly the _DECISION_SCHEMA keys
    assert set(record["assistant"]) == {"action", "reasoning", "added_delay_min"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dataset.py::test_build_record_matches_build_messages_and_schema -v`
Expected: FAIL with `ImportError: cannot import name 'build_record'`

- [ ] **Step 3: Write minimal implementation**

Append to `fleet/agent/dataset.py`:

```python
from fleet.contracts.state import DecisionAction
from fleet.agent.claude_agent import build_messages


def build_record(state: WorldState, event: Event, action: DecisionAction,
                 added_delay_min: float, reasoning: str) -> dict:
    """One JSONL row. Prompt fields come verbatim from build_messages (train/serve
    parity); the assistant turn is the strict _DECISION_SCHEMA object."""
    system, user = build_messages(state, event)
    return {
        "system": system,
        "user": user,
        "assistant": {
            "action": action.value,
            "reasoning": reasoning,
            "added_delay_min": round(float(added_delay_min), 2),
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dataset.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/dataset.py tests/test_dataset.py
git commit -m "feat(dataset): build_record — train/serve-parity JSONL row"
```

---

### Task 5: `grade_example` (oracle-graded best action + measured delay)

**Files:**
- Modify: `fleet/agent/dataset.py`
- Test: `tests/test_dataset.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dataset.py`:

```python
def test_grade_example_is_deterministic_and_returns_a_candidate():
    from config.settings import load_settings
    from fleet.contracts.state import Event, EventType, EventSeverity
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    from fleet.agent.scoring_engine import candidate_actions
    from fleet.agent.dataset import grade_example

    settings = load_settings({})
    state = build_sample_state()
    sim = WorldSimulator(settings)
    evt = Event(id="EVT_S", event_type=EventType.INVENTORY_SHORTAGE, target="SKU001",
                severity=EventSeverity.HIGH, started_at=state.clock)
    state.events.append(evt)

    action, delay, scored = grade_example(sim, state, evt, settings)
    assert action in candidate_actions(EventType.INVENTORY_SHORTAGE)
    assert delay >= 0.0
    assert [a for a, _ in scored] == sorted(
        candidate_actions(EventType.INVENTORY_SHORTAGE),
        key=lambda a: (dict(scored)[a], a.value))     # sorted by (cost, action.value)
    # determinism
    action2, delay2, scored2 = grade_example(sim, state, evt, settings)
    assert (action, delay, scored) == (action2, delay2, scored2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dataset.py::test_grade_example_is_deterministic_and_returns_a_candidate -v`
Expected: FAIL with `ImportError: cannot import name 'grade_example'`

- [ ] **Step 3: Write minimal implementation**

Append to `fleet/agent/dataset.py`:

```python
from fleet.contracts.state import Decision, DecisionEngine
from fleet.agent.scoring_engine import candidate_actions, _Weights
from fleet.agent.oracle import roll_forward, realized_cost


def grade_example(simulator, state: WorldState, event: Event, settings):
    """Roll every candidate action forward and grade by realized cost. Returns
    (best_action, best_realized_delay_min, scored) where scored is the full
    [(action, cost), ...] sorted by (cost, action.value)."""
    weights = _Weights(settings)
    horizon = settings.oracle_horizon_ticks
    results = []
    for a in candidate_actions(event.event_type):
        probe = Decision(
            id="ORACLE_PROBE", timestamp=state.clock, event_id=event.id, action=a,
            engine=DecisionEngine.RULE_BASED, description=f"oracle probe {a.value}")
        rolled = roll_forward(simulator, state, probe, horizon)
        results.append((a, realized_cost(rolled, weights),
                        realized_delay_minutes(rolled)))
    results.sort(key=lambda t: (t[1], t[0].value))
    best, _best_cost, best_delay = results[0]
    scored = [(a, c) for a, c, _ in results]
    return best, best_delay, scored
```

(Merge the new `Event`/`DecisionAction`/`Decision`/`DecisionEngine` imports into the single `from fleet.contracts.state import ...` line rather than keeping several separate imports from that module.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dataset.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/dataset.py tests/test_dataset.py
git commit -m "feat(dataset): grade_example — oracle best action + measured delay"
```

---

### Task 6: Scenario generation (`make_example` / `iter_examples`)

**Files:**
- Modify: `fleet/agent/dataset.py`
- Test: `tests/test_dataset.py`

The world must be **planned** before warm-up so that drop-style actions (DEFER/CANCEL/REALLOCATE) actually change the realized outcome — otherwise every candidate ties and the example is filtered out. Edge-targeted events (TRAFFIC/FLOODED_AREA) are still generated for coverage; many will be filtered because this simulator's movement is schedule-driven (that's expected and reported in Task 8).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dataset.py`:

```python
def test_make_example_injects_event_and_is_deterministic():
    from config.settings import load_settings
    from fleet.contracts.state import EventType, EventSeverity
    from fleet.factory import build_components
    from fleet.agent.dataset import make_example, DATASET_EVENT_SPECS

    settings = load_settings({})
    optimizer = build_components(settings).optimizer
    spec = (EventType.INVENTORY_SHORTAGE, EventSeverity.HIGH, "sku")

    sim1, state1, evt1 = make_example(7, spec, settings, optimizer)
    assert evt1 in state1.events                       # the event is present in the world
    assert evt1.event_type == EventType.INVENTORY_SHORTAGE
    assert state1.plan                                 # routes were solved

    # determinism: same seed+spec -> same injected event id + target
    sim2, state2, evt2 = make_example(7, spec, settings, optimizer)
    assert (evt2.id, evt2.target, evt2.severity) == (evt1.id, evt1.target, evt1.severity)


def test_iter_examples_spans_all_event_specs_per_seed():
    from config.settings import load_settings
    from fleet.factory import build_components
    from fleet.agent.dataset import iter_examples, DATASET_EVENT_SPECS

    settings = load_settings({})
    optimizer = build_components(settings).optimizer
    seen = {evt.event_type for _seed, (_sim, _state, evt)
            in iter_examples(settings, n_seeds=1, optimizer=optimizer)}
    assert seen == {spec[0] for spec in DATASET_EVENT_SPECS}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dataset.py::test_make_example_injects_event_and_is_deterministic -v`
Expected: FAIL with `ImportError: cannot import name 'make_example'`

- [ ] **Step 3: Write minimal implementation**

Append to `fleet/agent/dataset.py`:

```python
from dataclasses import replace

from fleet.contracts.state import EventType, EventSeverity
from fleet.scenarios import build_sample_state
from fleet.simulator.engine import WorldSimulator
from fleet.routing.planner import plan_routes

# (event_type, severity, target_kind) — spans all 4 disruption classes + severities.
DATASET_EVENT_SPECS = [
    (EventType.TRAFFIC, EventSeverity.MEDIUM, "edge"),
    (EventType.FLOODED_AREA, EventSeverity.HIGH, "edge"),
    (EventType.DEMAND_SURGE, EventSeverity.MEDIUM, "customer"),
    (EventType.URGENT_ORDER, EventSeverity.HIGH, "customer"),
    (EventType.INVENTORY_SHORTAGE, EventSeverity.HIGH, "sku"),
    (EventType.VEHICLE_BREAKDOWN, EventSeverity.CRITICAL, "vehicle"),
]


def _pick_target(state: WorldState, kind: str) -> str:
    """Deterministic target for an injected event (first id in sorted order)."""
    if kind == "edge":
        return sorted(state.road_graph.edges)[0]
    if kind == "customer":
        return sorted(state.customers)[0]
    if kind == "sku":
        return sorted(state.depot.inventory)[0]
    if kind == "vehicle":
        return sorted(state.vehicles)[0]
    raise ValueError(f"unknown target kind: {kind}")


def make_example(seed: int, spec, settings, optimizer, warmup_ticks: int = 6):
    """Build a planned, warmed-up world for one (seed, spec) and inject the event.
    Returns (simulator, state, event). Deterministic given the inputs."""
    s = replace(settings, seed=seed)
    state = build_sample_state()
    sim = WorldSimulator(s)
    plan_routes(state, optimizer)                 # solve routes so actions matter
    for _ in range(warmup_ticks):
        sim.tick(state)
    event_type, severity, kind = spec
    event = sim.inject_event(state, event_type, _pick_target(state, kind), severity)
    return sim, state, event


def iter_examples(settings, n_seeds: int, optimizer, warmup_ticks: int = 6):
    """Yield (seed, (simulator, state, event)) over seeds x DATASET_EVENT_SPECS."""
    for seed in range(settings.seed, settings.seed + n_seeds):
        for spec in DATASET_EVENT_SPECS:
            yield seed, make_example(seed, spec, settings, optimizer, warmup_ticks)
```

(Merge `EventType`/`EventSeverity` into the existing `from fleet.contracts.state import ...` line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dataset.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/dataset.py tests/test_dataset.py
git commit -m "feat(dataset): scenario generation — planned, seeded, spans all event specs"
```

---

### Task 7: `split_by_seed` + `batch_reasoning` (injected transport)

**Files:**
- Modify: `fleet/agent/dataset.py`
- Test: `tests/test_dataset.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dataset.py`:

```python
def test_split_by_seed_has_no_seed_leak():
    from fleet.agent.dataset import split_by_seed
    records = [(s, {"row": s}) for s in [1, 1, 2, 2, 3, 3, 4, 4]]
    train, test = split_by_seed(records, holdout_frac=0.25)
    train_seeds = {r["row"] for r in train}
    test_seeds = {r["row"] for r in test}
    assert test_seeds and not (train_seeds & test_seeds)   # disjoint -> no scenario leak
    assert test_seeds == {4}                                # last 25% of 4 seeds = seed 4


def test_batch_reasoning_falls_back_to_templated_per_missing_id():
    from fleet.contracts.state import Event, EventType, EventSeverity, DecisionAction
    from fleet.agent.dataset import batch_reasoning, templated_reasoning
    evt = Event(id="E1", event_type=EventType.DEMAND_SURGE, target="C001",
                severity=EventSeverity.MEDIUM, started_at=_BASE)
    scored = [(DecisionAction.REPRIORITIZE, 10.0), (DecisionAction.REALLOCATE, 30.0)]
    from fleet.scenarios import build_sample_state
    state = build_sample_state()
    examples = [
        {"custom_id": "ex-0", "state": state, "event": evt,
         "action": DecisionAction.REPRIORITIZE, "scored": scored},
        {"custom_id": "ex-1", "state": state, "event": evt,
         "action": DecisionAction.REPRIORITIZE, "scored": scored},
    ]

    # injected transport: only ex-0 gets a teacher reasoning
    def fake_submit(reqs):
        assert {r["custom_id"] for r in reqs} == {"ex-0", "ex-1"}
        return {"ex-0": "teacher says reprioritize."}

    out = batch_reasoning(examples, submit=fake_submit)
    assert out["ex-0"] == "teacher says reprioritize."
    assert out["ex-1"] == templated_reasoning(evt, scored)   # fallback

    # submit=None -> fully $0 templated path
    out0 = batch_reasoning(examples, submit=None)
    assert out0 == {"ex-0": templated_reasoning(evt, scored),
                    "ex-1": templated_reasoning(evt, scored)}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dataset.py::test_split_by_seed_has_no_seed_leak -v`
Expected: FAIL with `ImportError: cannot import name 'split_by_seed'`

- [ ] **Step 3: Write minimal implementation**

Append to `fleet/agent/dataset.py`:

```python
_REASONING_SYSTEM = (
    "You justify dispatch decisions for a real-time delivery-fleet system. Given a "
    "disruption event and the action that was chosen, write one or two sentences "
    "explaining why that action best protects on-time delivery and safety. Justify "
    "the GIVEN action; do not propose a different one.")


def split_by_seed(records, holdout_frac: float):
    """Split [(seed, record), ...] into (train, test) so no seed appears in both —
    the last ceil(holdout_frac * n_seeds) distinct seeds become the test set."""
    seeds = sorted({s for s, _ in records})
    n_test = max(1, round(holdout_frac * len(seeds))) if seeds else 0
    test_seeds = set(seeds[len(seeds) - n_test:]) if n_test else set()
    train = [r for s, r in records if s not in test_seeds]
    test = [r for s, r in records if s in test_seeds]
    return train, test


def _reasoning_prompt(state: WorldState, event: Event, action: DecisionAction) -> str:
    _system, user = build_messages(state, event)
    return (user + f"\n\nThe chosen action is: {action.value}. "
                   "Justify it in one or two sentences.")


def build_reasoning_requests(examples):
    """Transport-agnostic request descriptors (plain dicts) for the Batch transport."""
    return [{"custom_id": e["custom_id"], "system": _REASONING_SYSTEM,
             "user": _reasoning_prompt(e["state"], e["event"], e["action"])}
            for e in examples]


def batch_reasoning(examples, submit=None) -> dict:
    """Reasoning per example custom_id. `submit(requests) -> {custom_id: reasoning}`
    is injected (Sonnet Batch in production); any id the transport doesn't return —
    or submit=None — falls back to the $0 templated reasoning."""
    raw = {}
    if submit is not None and examples:
        raw = submit(build_reasoning_requests(examples)) or {}
    out = {}
    for e in examples:
        cid = e["custom_id"]
        out[cid] = raw.get(cid) or templated_reasoning(e["event"], e["scored"])
    return out


def default_batch_submit(settings):
    """Lazy real transport: Sonnet 4.6 via the Message Batches API (thinking off,
    guided-JSON reasoning). Imported here so the suite never needs anthropic."""
    import json
    import time
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    client = anthropic.Anthropic(api_key=(settings.anthropic_api_key or None))
    schema = {"type": "object", "properties": {"reasoning": {"type": "string"}},
              "required": ["reasoning"], "additionalProperties": False}

    def submit(reqs):
        batch = client.messages.batches.create(requests=[
            Request(custom_id=r["custom_id"],
                    params=MessageCreateParamsNonStreaming(
                        model="claude-sonnet-4-6", max_tokens=256,
                        thinking={"type": "disabled"}, system=r["system"],
                        output_config={"format": {"type": "json_schema",
                                                   "schema": schema}},
                        messages=[{"role": "user", "content": r["user"]}]))
            for r in reqs])
        while client.messages.batches.retrieve(batch.id).processing_status != "ended":
            time.sleep(30)
        out = {}
        for res in client.messages.batches.results(batch.id):
            if res.result.type == "succeeded":
                msg = res.result.message
                text = next((b.text for b in msg.content if b.type == "text"), "")
                try:
                    out[res.custom_id] = json.loads(text).get("reasoning", "")
                except Exception:
                    pass
        return out

    return submit
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dataset.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/dataset.py tests/test_dataset.py
git commit -m "feat(dataset): split_by_seed + batch_reasoning (injected Sonnet-Batch transport)"
```

---

### Task 8: `scripts/gen_dataset.py` CLI + smoke + regression

**Files:**
- Create: `scripts/gen_dataset.py`
- Create: `scripts/__init__.py` (empty, so the smoke test can import the module)
- Test: `tests/test_gen_dataset.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gen_dataset.py`:

```python
import json
from pathlib import Path

from config.settings import load_settings


def test_build_dataset_writes_split_jsonl_with_oracle_labels(tmp_path):
    from scripts.gen_dataset import build_dataset

    settings = load_settings({})
    out = build_dataset(settings, n_seeds=2, out_dir=str(tmp_path),
                        holdout_frac=0.5, use_teacher=False)   # $0 templated path

    train_path = Path(tmp_path) / "train.jsonl"
    test_path = Path(tmp_path) / "test.jsonl"
    assert train_path.exists() and test_path.exists()

    train_rows = [json.loads(l) for l in train_path.read_text().splitlines() if l]
    assert train_rows, "expected at least one informative training example"
    row = train_rows[0]
    assert set(row) == {"system", "user", "assistant"}
    assert set(row["assistant"]) == {"action", "reasoning", "added_delay_min"}

    # report carries coverage + informative fraction
    assert out["n_train"] == len(train_rows)
    assert 0.0 <= out["informative_fraction"] <= 1.0
    assert out["event_types"]                     # coverage by event type, non-empty


def test_build_dataset_is_deterministic(tmp_path):
    from scripts.gen_dataset import build_dataset
    settings = load_settings({})
    a = build_dataset(settings, n_seeds=2, out_dir=str(tmp_path / "a"),
                      holdout_frac=0.5, use_teacher=False)
    b = build_dataset(settings, n_seeds=2, out_dir=str(tmp_path / "b"),
                      holdout_frac=0.5, use_teacher=False)
    assert (Path(tmp_path / "a" / "train.jsonl").read_text()
            == Path(tmp_path / "b" / "train.jsonl").read_text())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gen_dataset.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.gen_dataset'`

- [ ] **Step 3: Write minimal implementation**

Create empty `scripts/__init__.py`:

```python
```

Create `scripts/gen_dataset.py`:

```python
"""Offline data factory for Sovereign Brain v2 (M-B). Drives the simulator over
seeded scenarios, grades candidate actions with the oracle, keeps informative
oracle-verified labels, attaches reasoning (templated $0 by default, or Sonnet
Batch with --use-teacher), and writes seed-split train/test JSONL.

Usage:
  python -m scripts.gen_dataset --seeds 200 --out data/sovereign-brain
  python -m scripts.gen_dataset --seeds 200 --out data/sovereign-brain --use-teacher
"""

import argparse
import json
import os

from config.settings import load_settings
from fleet.factory import build_components
from fleet.agent.dataset import (
    iter_examples, grade_example, is_informative, build_record, batch_reasoning,
    split_by_seed, default_batch_submit,
)


def build_dataset(settings, n_seeds, out_dir, holdout_frac=0.2, use_teacher=False):
    """Generate the dataset and write {train,test}.jsonl under out_dir. Returns a
    report dict (counts, informative fraction, per-event-type coverage)."""
    optimizer = build_components(settings).optimizer

    graded = []          # (seed, state, event, action, delay, scored)
    n_total = 0
    for seed, (sim, state, event) in iter_examples(settings, n_seeds, optimizer):
        n_total += 1
        action, delay, scored = grade_example(sim, state, event, settings)
        if is_informative(scored, settings.oracle_min_gap):
            graded.append((seed, state, event, action, delay, scored))

    # reasoning (teacher or $0 templated), keyed by a stable custom_id
    examples = [{"custom_id": f"ex-{i}", "state": st, "event": ev,
                 "action": ac, "scored": sc}
                for i, (_seed, st, ev, ac, _dl, sc) in enumerate(graded)]
    submit = default_batch_submit(settings) if use_teacher else None
    reasonings = batch_reasoning(examples, submit=submit)

    records = []         # (seed, record)
    for i, (seed, st, ev, ac, dl, _sc) in enumerate(graded):
        rec = build_record(st, ev, ac, dl, reasonings[f"ex-{i}"])
        records.append((seed, rec))

    train, test = split_by_seed(records, holdout_frac)

    os.makedirs(out_dir, exist_ok=True)
    _write_jsonl(os.path.join(out_dir, "train.jsonl"), train)
    _write_jsonl(os.path.join(out_dir, "test.jsonl"), test)

    coverage = {}
    for _seed, _st, ev, _ac, _dl, _sc in graded:
        coverage[ev.event_type.value] = coverage.get(ev.event_type.value, 0) + 1

    return {
        "n_total": n_total,
        "n_informative": len(graded),
        "informative_fraction": (len(graded) / n_total) if n_total else 0.0,
        "n_train": len(train),
        "n_test": len(test),
        "event_types": coverage,
    }


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=200)
    p.add_argument("--out", default="data/sovereign-brain")
    p.add_argument("--holdout-frac", type=float, default=0.2)
    p.add_argument("--use-teacher", action="store_true",
                   help="label reasoning via Sonnet 4.6 Batch (needs ANTHROPIC_API_KEY)")
    args = p.parse_args()

    report = build_dataset(load_settings(), args.seeds, args.out,
                           args.holdout_frac, args.use_teacher)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gen_dataset.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite + a real tiny generation smoke**

Run: `pytest -q`
Expected: PASS — prior count plus the new `test_dataset.py` (11) + `test_gen_dataset.py` (2) + `test_config.py` (1). No previously-passing test changes status (dataset code is offline-only; the loop never imports it).

Run: `python -m scripts.gen_dataset --seeds 3 --out data/_smoke`
Expected: prints a JSON report with `n_total`, `n_informative`, `informative_fraction`, and an `event_types` map; writes `data/_smoke/train.jsonl` + `data/_smoke/test.jsonl`. No network call (templated reasoning). Delete `data/_smoke` afterward — it's a scratch artifact, not committed.

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/gen_dataset.py tests/test_gen_dataset.py
git commit -m "feat(dataset): gen_dataset.py CLI — oracle-verified seed-split JSONL ($0 default)"
```

---

## Self-Review

**Spec coverage (vs `2026-06-07-sovereign-brain-v2-oracle-design.md` §4.1–4.5, §10 M-B):**
- §4.1 N seeded scenarios spanning the 4 disruption classes + severities → Task 6 (`DATASET_EVENT_SPECS`, `iter_examples`). ✓
- §4.2/§4.3 oracle grade + informative-gap filter (`oracle_min_gap`, drop ties) → Tasks 1, 2 (`is_informative`), 5 (`grade_example`), 8 (filter wired). ✓
- §4.4 train/serve parity (`build_messages` verbatim), strict `_DECISION_SCHEMA` assistant turn, **measured** `added_delay_min`, reasoning conditioned on the oracle action (Sonnet Batch) + `$0` templated fallback, held-out split by seed → Tasks 3, 4, 5 (delay), 7 (`batch_reasoning`, `_REASONING_SYSTEM`, `split_by_seed`), 8. ✓
- §4.5 oracle compute = CPU/$0; reasoning labels via Sonnet 4.6 Batch, thinking off, guided-JSON → `default_batch_submit` (Task 7). Token-count validation (`messages.count_tokens`) before a paid run is documented in the spec; the `--use-teacher` flag gates all spend and defaults off, so no batch is created without the operator opting in. ✓
- §7 boundary: pure CPU module, suite never imports anthropic / hits network (transport injected; `default_batch_submit` imports lazily) → Tasks 2–8; Task 8 Step 5 proves the loop is untouched. ✓
- §10 M-B "JSONL + held-out split by seed + coverage + informative-fraction report" → `build_dataset` report (Task 8). ✓

**Placeholder scan:** No TBD/TODO; every code step is complete; every command has expected output.

**Type consistency:** `scored` is consistently `[(DecisionAction, float)]` across `is_informative`/`templated_reasoning`/`grade_example`/`batch_reasoning`. `grade_example(...) -> (action, delay, scored)`, `build_record(state, event, action, added_delay_min, reasoning) -> dict`, `make_example(seed, spec, settings, optimizer, warmup_ticks=6) -> (sim, state, event)`, `iter_examples(settings, n_seeds, optimizer, warmup_ticks=6)`, `split_by_seed(records, holdout_frac) -> (train, test)`, `batch_reasoning(examples, submit=None) -> dict`, `build_dataset(settings, n_seeds, out_dir, holdout_frac, use_teacher) -> report` are used identically in the tests and the script. `examples` dicts always carry `custom_id`/`state`/`event`/`action`/`scored`. Reuses M-A's `roll_forward`/`realized_cost` and the shipped `build_messages`/`candidate_actions`/`_Weights`/`plan_routes`/`build_components` without changing them.

**Dependency note:** This plan assumes **M-A (`fleet/agent/oracle.py`)** is merged (it is — `grade_example` imports `roll_forward`/`realized_cost`). `make_example`/`iter_examples`/`build_dataset` tests use the real `CpuSolver` (OR-Tools), already a suite dependency. Edge-targeted specs (TRAFFIC/FLOODED_AREA) are commonly filtered out because this simulator's vehicle movement is schedule-driven (edge state doesn't change travel) — the informative-fraction report surfaces this honestly; faithful REROUTE/RESCHEDULE grading via a `resolve` re-solve hook is the documented stretch, not M-B scope.
