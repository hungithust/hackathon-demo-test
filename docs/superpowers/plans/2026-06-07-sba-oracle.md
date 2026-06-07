# Sovereign Brain v2 — M-A Oracle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the simulator-as-oracle grader — clone the world, apply a candidate action, roll the simulation forward, and measure the *realized* cost — so later milestones can label decisions by outcome instead of by heuristic.

**Architecture:** One new pure module `fleet/agent/oracle.py`. `realized_cost(state, weights)` reads the world's actual outcome (late minutes, priority-weighted undelivered orders, breached customers) reusing the M-D `ScoringEngine` weights so cost stays in one unit. `roll_forward(sim, state, decision, horizon, resolve=None)` deep-copies `(simulator, state, decision)` **together** (so the seeded RNG is cloned and every candidate sees an identical future), applies the decision via the existing `Dispatcher`, optionally re-solves, then ticks `horizon` times. `grade_action` / `best_action` wrap these to score candidate actions and pick the cheapest. CPU-only, deterministic, no GPU/network — the test suite never leaves the process.

**Tech Stack:** Python, `copy.deepcopy`, existing `WorldSimulator` / `Dispatcher` / `ScoringEngine._Weights`, pytest.

---

### Task 1: Oracle horizon setting

**Files:**
- Modify: `config/settings.py:50` (add field after `enable_proactive`)
- Modify: `config/settings.py:98` (add the `load_settings` line)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_oracle_horizon_default_and_override():
    from config.settings import load_settings
    assert load_settings({}).oracle_horizon_ticks == 12
    assert load_settings({"ORACLE_HORIZON_TICKS": "6"}).oracle_horizon_ticks == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_oracle_horizon_default_and_override -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'oracle_horizon_ticks'`

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add a field at the end of the `Settings` dataclass (right after the `enable_proactive` line):

```python
    oracle_horizon_ticks: int = 12        # M-A(SBv2): ticks to roll a candidate action forward before grading
```

In `load_settings`, add this line just before the closing `)` of the `Settings(...)` call (after the `enable_proactive=...` line):

```python
        oracle_horizon_ticks=int(e.get("ORACLE_HORIZON_TICKS", "12")),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py::test_oracle_horizon_default_and_override -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_config.py
git commit -m "feat(oracle): oracle_horizon_ticks setting (roll-forward horizon)"
```

---

### Task 2: `realized_cost` — pure outcome reader

**Files:**
- Create: `fleet/agent/oracle.py`
- Test: `tests/test_oracle.py`

The cost reuses the M-D weights (`score_w_sla / score_w_delay / score_w_drop` via `ScoringEngine._Weights`) so the oracle and the scoring engine speak the same unit. Lower is better:

```
cost = w_delay * (total late-minutes across delivered stops past their window)
     + w_drop  * (priority-weighted undelivered order units)
     + w_sla   * (number of customers with a breach: late OR undelivered)
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_oracle.py`:

```python
from datetime import datetime, timedelta

from config.settings import load_settings
from fleet.contracts.state import (
    WorldState, Depot, Location, CustomerProfile, TimeWindow, Stop, VehicleRoute,
)
from fleet.agent.scoring_engine import _Weights
from fleet.agent.oracle import realized_cost

_BASE = datetime(2026, 6, 4, 6, 0)


def _depot():
    return Depot(location=Location(0.0, 0.0, "d", "d"), inventory={},
                 opening_time=_BASE, closing_time=_BASE + timedelta(hours=12))


def _customer(orders, priority=1, window_hours=2):
    return CustomerProfile(
        id="C1", type="market", location=Location(0.0, 0.0, "c", "c"),
        orders=dict(orders), priority=priority,
        time_window=TimeWindow(_BASE, _BASE + timedelta(hours=window_hours)))


def test_realized_cost_counts_priority_weighted_drops():
    st = WorldState(clock=_BASE, depot=_depot(),
                    customers={"C1": _customer({"SKU001": 5}, priority=1)})
    w = _Weights(load_settings({}))
    # priority 1 -> weight 4; 5 undelivered units; 1 breached customer
    # cost = w_drop*4*5 + w_sla*1 = 50*20 + 50*1 = 1050
    assert realized_cost(st, w) == 1050.0


def test_realized_cost_zero_when_delivered_on_time():
    cust = _customer({}, priority=1)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1))
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    w = _Weights(load_settings({}))
    assert realized_cost(st, w) == 0.0


def test_realized_cost_charges_late_delivery():
    cust = _customer({}, priority=2, window_hours=1)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1, minutes=30))  # 30 min late
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    w = _Weights(load_settings({}))
    # late 30 min, 1 breached customer, no drops -> 1*30 + 50*1 = 80
    assert realized_cost(st, w) == 80.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.agent.oracle'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/agent/oracle.py`:

```python
"""Simulator-as-oracle grader (Sovereign Brain v2, M-A). Instead of scoring an
action by a hardcoded effect table, *apply it to a clone of the world, roll the
simulation forward, and measure what actually happened*. `realized_cost` reads
that outcome reusing the M-D ScoringEngine weights so cost is in one unit.
Pure CPU, deterministic, no GPU/network — safe in the test suite."""

from fleet.contracts.state import WorldState
from fleet.agent.scoring_engine import _Weights


def _priority_weight(priority: int) -> float:
    """Priority 1 (most urgent) -> 4 ... priority 4 -> 1. Mirrors the
    per-customer form of scoring_engine._priority_weight."""
    return float(5 - int(priority))


def realized_cost(state: WorldState, weights: "_Weights") -> float:
    """The world's ACTUAL outcome after a roll-forward; lower is better.

    cost = w_delay * total late-minutes (delivered stops past their window)
         + w_drop  * priority-weighted undelivered order units
         + w_sla   * count of customers with a breach (late OR undelivered)."""
    late_minutes = 0.0
    breached: set = set()

    for route in state.plan.values():
        for stop in route.stops:
            if stop.actual_arrival is None:
                continue
            cust = state.customers.get(stop.customer_id)
            if cust is None:
                continue
            overdue = (stop.actual_arrival - cust.time_window.end).total_seconds() / 60.0
            if overdue > 0:
                late_minutes += overdue
                breached.add(cust.id)

    drop_cost = 0.0
    for cid, cust in state.customers.items():
        units = sum(cust.orders.values())
        if units > 0:
            drop_cost += _priority_weight(cust.priority) * units
            breached.add(cid)

    return (weights.delay * late_minutes
            + weights.drop * drop_cost
            + weights.sla * float(len(breached)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/oracle.py tests/test_oracle.py
git commit -m "feat(oracle): realized_cost — outcome reader (late/drops/breach, ScoringEngine weights)"
```

---

### Task 3: `roll_forward` — clone, apply, tick (deterministic & pure)

**Files:**
- Modify: `fleet/agent/oracle.py`
- Test: `tests/test_oracle.py`

This is the load-bearing assumption of the whole flagship: `deepcopy((simulator, state, decision))` clones the seeded RNG with the world, so two branches with the same action see an **identical future**, and the original objects are never mutated.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_oracle.py`:

```python
def test_roll_forward_is_deterministic_and_pure():
    from fleet.contracts.state import Decision, DecisionAction, DecisionEngine
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    from fleet.agent.oracle import roll_forward

    settings = load_settings({})
    state = build_sample_state()
    sim = WorldSimulator(settings)
    dec = Decision(id="D", timestamp=state.clock, event_id=None,
                   action=DecisionAction.REPRIORITIZE,
                   engine=DecisionEngine.RULE_BASED, description="probe")
    before_clock = state.clock
    w = _Weights(settings)

    r1 = roll_forward(sim, state, dec, horizon=5)
    r2 = roll_forward(sim, state, dec, horizon=5)

    assert realized_cost(r1, w) == realized_cost(r2, w)   # identical future across branches
    assert r1.clock > before_clock                         # the clone advanced 5 ticks
    assert state.clock == before_clock                     # original state untouched
    assert state.sim_tick == 0                             # original simulator state untouched
    assert dec.executed_at is None                         # caller's decision untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle.py::test_roll_forward_is_deterministic_and_pure -v`
Expected: FAIL with `ImportError: cannot import name 'roll_forward'`

- [ ] **Step 3: Write minimal implementation**

Add to `fleet/agent/oracle.py` — extend the imports at the top and append the function:

```python
import copy
from typing import Callable, Optional

from fleet.contracts.state import WorldState, Decision
from fleet.dispatch.dispatcher import Dispatcher, RESOLVE_ACTIONS
```

```python
def roll_forward(simulator, state: WorldState, decision: Decision, horizon: int,
                 resolve: Optional[Callable[[WorldState], None]] = None) -> WorldState:
    """Clone (simulator, state, decision) TOGETHER — so the seeded rng is cloned
    with the world and every candidate sees an identical future — then apply the
    decision, optionally re-solve (resolve callback, only for RESOLVE_ACTIONS),
    and tick `horizon` times. Returns the rolled-forward clone; inputs are never
    mutated."""
    sim_c, state_c, dec_c = copy.deepcopy((simulator, state, decision))
    Dispatcher().apply(state_c, dec_c)
    if resolve is not None and dec_c.action in RESOLVE_ACTIONS:
        resolve(state_c)
    for _ in range(horizon):
        sim_c.tick(state_c)
    return state_c
```

Keep the existing `from fleet.agent.scoring_engine import _Weights` import; just add the new import lines above it (do not duplicate the `WorldState` import — merge it into the new `from fleet.contracts.state import WorldState, Decision` line and delete the old single-name import).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/oracle.py tests/test_oracle.py
git commit -m "feat(oracle): roll_forward — clone(sim,state,decision)+apply+tick, deterministic & pure"
```

---

### Task 4: `grade_action` / `best_action` — score candidates, pick cheapest

**Files:**
- Modify: `fleet/agent/oracle.py`
- Test: `tests/test_oracle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_oracle.py`:

```python
def test_best_action_is_sorted_and_deterministic():
    from fleet.contracts.state import (
        Event, EventType, EventSeverity, DecisionAction,
    )
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    from fleet.agent.scoring_engine import candidate_actions
    from fleet.agent.oracle import best_action

    settings = load_settings({})
    state = build_sample_state()
    sim = WorldSimulator(settings)
    evt = Event(id="EVT_X", event_type=EventType.INVENTORY_SHORTAGE,
                target="SKU001", severity=EventSeverity.HIGH, started_at=state.clock)
    state.events.append(evt)
    cands = candidate_actions(evt.event_type)

    best, cost, scored = best_action(sim, state, evt, cands, settings, horizon=6)

    assert best in cands
    assert [a for a, _ in scored] == sorted(  # min cost, stable tie-break by action.value
        (a for a in cands),
        key=lambda a: (dict((aa, cc) for aa, cc in scored)[a], a.value))
    assert scored[0][1] <= scored[-1][1]
    # determinism: identical inputs -> identical pick + cost
    best2, cost2, _ = best_action(sim, state, evt, cands, settings, horizon=6)
    assert (best, cost) == (best2, cost2)


def test_grade_action_defaults_horizon_from_settings():
    from fleet.contracts.state import (
        Event, EventType, EventSeverity, DecisionAction,
    )
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    from fleet.agent.oracle import grade_action

    settings = load_settings({"ORACLE_HORIZON_TICKS": "3"})
    state = build_sample_state()
    sim = WorldSimulator(settings)
    evt = Event(id="EVT_Y", event_type=EventType.DEMAND_SURGE, target="C001",
                severity=EventSeverity.MEDIUM, started_at=state.clock)
    state.events.append(evt)
    # no horizon arg -> uses settings.oracle_horizon_ticks; returns a finite cost
    cost = grade_action(sim, state, evt, DecisionAction.REPRIORITIZE, settings)
    assert isinstance(cost, float) and cost >= 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_oracle.py::test_best_action_is_sorted_and_deterministic -v`
Expected: FAIL with `ImportError: cannot import name 'best_action'`

- [ ] **Step 3: Write minimal implementation**

Add to `fleet/agent/oracle.py` — extend the contracts import and append the two functions:

```python
from fleet.contracts.state import (
    WorldState, Decision, DecisionAction, DecisionEngine, Event,
)
```

```python
def grade_action(simulator, state: WorldState, event: Event,
                 action: DecisionAction, settings, horizon: Optional[int] = None,
                 resolve: Optional[Callable[[WorldState], None]] = None) -> float:
    """Realized cost of taking `action` in response to `event`. Builds a probe
    Decision, rolls it forward, and grades the outcome. Horizon defaults to
    settings.oracle_horizon_ticks."""
    h = settings.oracle_horizon_ticks if horizon is None else horizon
    probe = Decision(
        id="ORACLE_PROBE", timestamp=state.clock, event_id=event.id, action=action,
        engine=DecisionEngine.RULE_BASED, description=f"oracle probe {action.value}")
    rolled = roll_forward(simulator, state, probe, h, resolve)
    return realized_cost(rolled, _Weights(settings))


def best_action(simulator, state: WorldState, event: Event, candidates, settings,
                horizon: Optional[int] = None,
                resolve: Optional[Callable[[WorldState], None]] = None):
    """Grade every candidate and return (best_action, best_cost, scored) where
    `scored` is the full [(action, cost), ...] list sorted by (cost, action.value)."""
    scored = sorted(
        ((a, grade_action(simulator, state, event, a, settings, horizon, resolve))
         for a in candidates),
        key=lambda t: (t[1], t[0].value))
    best, cost = scored[0]
    return best, cost, scored
```

Merge the extended `from fleet.contracts.state import (...)` into the single existing contracts import line (do not keep two imports from that module).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_oracle.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/oracle.py tests/test_oracle.py
git commit -m "feat(oracle): grade_action + best_action over candidate actions (sorted, deterministic)"
```

---

### Task 5: Full-suite regression + loop smoke

**Files:**
- No code changes — this task verifies the oracle is purely additive (no existing test or runtime path changed).

- [ ] **Step 1: Run the whole suite**

Run: `pytest -q`
Expected: PASS — the prior count plus the 7 new tests (1 in `test_config.py`, 6 in `test_oracle.py`). No previously-passing test changes status.

- [ ] **Step 2: Smoke the headless loop (oracle must not touch the runtime path)**

Run: `python -m fleet.loop`
Expected: clean run, no traceback. The oracle is offline-only; the loop output is byte-identical to before this milestone (default `decision_engine="rule"`, oracle never imported by the loop).

- [ ] **Step 3: Commit (only if any incidental fix was needed; otherwise skip)**

If `pytest -q` and the smoke run were already green with no edits, there is nothing to commit — this task is a verification gate, not a code change.

---

## Self-Review

**Spec coverage (vs `2026-06-07-sovereign-brain-v2-oracle-design.md` §4.2–4.3, §7, §10 M-A):**
- §4.2 clone `(simulator, state)` incl. rng, apply, tick×horizon, realized cost reusing ScoringEngine weights → Tasks 2–4. ✓
- §4.2 fairness pillar (identical future across branches; clone the simulator, not just state) → Task 3 determinism+purity test. ✓
- §4.3 horizon configurable → Task 1 (`oracle_horizon_ticks`); the "all-candidates-tie → drop / `oracle_min_gap`" filter is **M-B's** dataset concern (filtering happens when assembling JSONL), correctly out of M-A scope. ✓
- §7 boundary: `oracle.py` pure/CPU, test suite never needs GPU/network; only offline use → Task 5 smoke proves the runtime path is untouched. ✓
- §10 M-A "verify deepcopy cleanliness + identical-future fairness, no GPU" → Task 3. ✓
- `resolve` hook is provided (default `None`) so M-B can pass the planner's reroute for faithful REROUTE/RESCHEDULE grading; without it those actions are graded on their post-dispatch state (acceptable for M-A, which proves the machinery). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output.

**Type consistency:** `realized_cost(state, weights)`, `roll_forward(simulator, state, decision, horizon, resolve=None)`, `grade_action(..., horizon=None, resolve=None) -> float`, `best_action(...) -> (action, cost, scored)` are consistent across Tasks 2–4 and used identically in the tests. `_Weights` attributes (`.delay/.drop/.sla`) match `fleet/agent/scoring_engine.py`. `Settings.oracle_horizon_ticks` (Task 1) is the attribute `grade_action` reads (Task 4). Imports are merged, not duplicated, across Tasks 2–4.
