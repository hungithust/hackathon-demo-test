# SBv2 M-F: Consequential Disruptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make disruptions actually change the simulated outcome so the oracle can distinguish candidate actions for all six event types — not just `inventory_shortage`.

**Architecture:** A default-off `enable_travel_time` flag turns `_advance_vehicles` into a matrix-replay over the *live* road graph (blocked/flooded/congested edges delay or prevent arrivals). A grading-only `advance_only` flag freezes exogenous demand during roll-forward. The dataset factory gains a `make_disrupted_example` that injures the world per event type, and a `grade_disrupted` that grades with travel-time + frozen demand + re-solve. Everything is gated so the existing 52 SBv2 tests stay green.

**Tech Stack:** Python 3.12, pytest, existing `fleet.routing.matrix.shortest_times_from` (Dijkstra over live edges), `fleet.routing.planner.reroute`, `copy.deepcopy`-based oracle.

**Spec:** `docs/superpowers/specs/2026-06-07-sbf-consequential-disruptions-design.md`

**Run tests with:** `python -m pytest <path> -q` (on the org machine; locally the same suite is green via the project's interpreter).

---

## File Structure

- Modify `config/settings.py` — add `enable_travel_time` setting (Task 1).
- Modify `fleet/simulator/engine.py` — travel-time movement branch + `advance_only` freeze (Tasks 2–3).
- Modify `fleet/agent/oracle.py` — `roll_forward(freeze_world=...)` (Task 4).
- Modify `fleet/agent/dataset.py` — `_critical_edges`, `make_disrupted_example`, `grade_disrupted`, `iter_disrupted_examples` (Task 5).
- Modify `scripts/gen_dataset.py` — `--consequential` path + per-type coverage (Task 6).
- Tests: `tests/test_config.py`, `tests/test_travel_time.py` (new), `tests/test_oracle.py`, `tests/test_dataset.py`, `tests/test_gen_dataset.py`.

---

### Task 1: `enable_travel_time` setting

**Files:**
- Modify: `config/settings.py:53-54` (add field after `nim_model`), `config/settings.py:105-106` (add env load)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_enable_travel_time_default_off_and_env_on():
    from config.settings import load_settings
    assert load_settings({}).enable_travel_time is False
    assert load_settings({"ENABLE_TRAVEL_TIME": "1"}).enable_travel_time is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_enable_travel_time_default_off_and_env_on -q`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'enable_travel_time'`

- [ ] **Step 3: Add the field**

In `config/settings.py`, in the `Settings` dataclass right after the `nim_model` field (around line 54), add:

```python
    enable_travel_time: bool = False      # M-F(SBv2): travel-time-aware movement (default off keeps schedule-driven behavior)
```

In `load_settings`, right after the `nim_model=...` line (around line 106), add:

```python
        enable_travel_time=e.get("ENABLE_TRAVEL_TIME", "0") in ("1", "true", "True"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py::test_enable_travel_time_default_off_and_env_on -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_config.py
git commit -m "feat(settings): enable_travel_time flag (M-F, default off)"
```

---

### Task 2: Travel-time-aware movement

**Files:**
- Modify: `fleet/simulator/engine.py` (add import, add `_advance` dispatch + `_advance_vehicles_travel_time`, change `tick` to call `_advance`)
- Test: `tests/test_travel_time.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_travel_time.py`:

```python
"""M-F: travel-time-aware movement responds to live edge disruptions."""

from dataclasses import replace

from config.settings import load_settings
from fleet.scenarios import build_sample_state
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.planner import plan_routes
from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import EdgeStatus


def _delivered_customers(enable_travel_time: bool) -> set:
    settings = replace(load_settings({}), enable_travel_time=enable_travel_time)
    state = build_sample_state()
    plan_routes(state, CpuSolver(settings))
    # cut every in-edge to C001 -> unreachable on the live graph
    for eid in ("DEPOT->C001", "DEPOT->C001#2", "C002->C001"):
        edge = state.road_graph.get_edge(eid)
        if edge is not None:
            edge.status = EdgeStatus.BLOCKED
    sim = WorldSimulator(settings)
    for _ in range(72):
        sim.tick(state)
    return {s.customer_id for r in state.plan.values()
            for s in r.stops if s.actual_arrival is not None}


def test_schedule_driven_ignores_blocked_edges():
    # Default movement is schedule-driven: it delivers C001 regardless of edges.
    assert "C001" in _delivered_customers(enable_travel_time=False)


def test_travel_time_leaves_unreachable_customer_undelivered():
    # Travel-time movement respects the live graph: an isolated C001 is not served.
    assert "C001" not in _delivered_customers(enable_travel_time=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_travel_time.py -q`
Expected: `test_travel_time_leaves_unreachable_customer_undelivered` FAILS (C001 still delivered because movement ignores edges).

- [ ] **Step 3: Implement travel-time movement**

In `fleet/simulator/engine.py`, add the import near the top (after the existing `from fleet.contracts.state import (...)` block):

```python
from fleet.routing.matrix import shortest_times_from, DEFAULT_SERVICE_TIME_MIN
```

In `WorldSimulator.tick`, change the final line from:

```python
        self._advance_vehicles(state)
```

to:

```python
        self._advance(state)
```

Add this dispatch method (place it just above `_advance_vehicles`):

```python
    def _advance(self, state: WorldState) -> None:
        """Move vehicles for this tick. Travel-time-aware when enabled (M-F),
        else the default schedule-driven behavior."""
        if getattr(self.settings, "enable_travel_time", False):
            self._advance_vehicles_travel_time(state)
        else:
            self._advance_vehicles(state)
```

Add the travel-time mover (place it directly after `_advance_vehicles`):

```python
    def _advance_vehicles_travel_time(self, state: WorldState) -> None:
        """Replay each route against the LIVE road graph (M-F) so disruptions
        actually delay or prevent arrivals. A vehicle's current node and time are
        derived each tick from its already-visited stops, so no persistent state
        is added. A blocked/flooded edge that isolates a stop leaves it
        undelivered until a re-solve reroutes; a congested/flooded edge raises
        effective travel time -> later actual_arrival -> real lateness."""
        graph = state.road_graph
        for vid, route in state.plan.items():
            vehicle = state.vehicles.get(vid)
            if vehicle is None or vehicle.status in (
                    VehicleStatus.BROKEN, VehicleStatus.MAINTENANCE):
                continue
            visited = [s for s in route.stops if s.actual_arrival is not None]
            if visited:
                cur_node = visited[-1].customer_id
                cur_time = visited[-1].actual_departure
            else:
                cur_node = "DEPOT"
                cur_time = state.depot.opening_time
            for stop in route.stops:
                if stop.actual_arrival is not None:
                    continue
                dist = shortest_times_from(graph, cur_node, vehicle.wade_capability)
                target = stop.customer_id
                if target not in dist:           # unreachable on the live graph
                    break                        # vehicle is stuck until a re-solve
                arrival = cur_time + timedelta(minutes=dist[target])
                if arrival <= state.clock:
                    stop.actual_arrival = arrival
                    stop.actual_departure = arrival + timedelta(
                        minutes=DEFAULT_SERVICE_TIME_MIN)
                    cust = state.customers.get(target)
                    if cust is not None:
                        vehicle.pos = cust.location
                    vehicle.current_stop_index = stop.sequence
                    vehicle.status = VehicleStatus.ON_ROUTE
                    self._deliver(state, vehicle, target)
                    cur_node = target
                    cur_time = stop.actual_departure
                else:
                    break                        # not reached yet this tick
            all_visited = route.stops and all(
                s.actual_arrival is not None for s in route.stops)
            shift_done = route.end_time is None or state.clock >= route.end_time
            if all_visited and shift_done:
                vehicle.status = VehicleStatus.AT_DEPOT
                vehicle.pos = state.depot.location
                vehicle.current_stop_index = -1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_travel_time.py -q`
Expected: both PASS.

Run the regression guard (schedule-driven path must be untouched):
Run: `python -m pytest tests/test_movement.py tests/test_loop.py tests/test_simulator.py -q`
Expected: all PASS (default `enable_travel_time=False`).

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_travel_time.py
git commit -m "feat(sim): travel-time-aware movement (matrix-replay, M-F, gated)"
```

---

### Task 3: `advance_only` freeze flag

**Files:**
- Modify: `fleet/simulator/engine.py` (`__init__` attribute + early-return branch in `tick`)
- Test: `tests/test_travel_time.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_travel_time.py`:

```python
def test_advance_only_freezes_exogenous_world():
    from config.settings import load_settings
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    settings = load_settings({})
    state = build_sample_state()
    sim = WorldSimulator(settings)
    sim.advance_only = True
    pending_before = state.total_orders_pending()
    events_before = len(state.events)
    for _ in range(10):
        sim.tick(state)
    # no new demand, no new shortage/weather events; clock still advances
    assert state.total_orders_pending() == pending_before
    assert len(state.events) == events_before
    assert state.sim_tick == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_travel_time.py::test_advance_only_freezes_exogenous_world -q`
Expected: FAIL — either `AttributeError: ... 'advance_only'` is tolerated by the assignment, but `tick` still generates demand so `total_orders_pending()` increases.

- [ ] **Step 3: Implement the freeze flag**

In `fleet/simulator/engine.py`, in `WorldSimulator.__init__`, add at the end of the method:

```python
        self.advance_only = False    # M-F: grading-only — tick advances vehicles only
```

In `WorldSimulator.tick`, immediately after the two opening lines that advance the clock and `sim_tick`:

```python
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1
```

insert:

```python
        if self.advance_only:
            self._advance(state)
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_travel_time.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_travel_time.py
git commit -m "feat(sim): advance_only freeze flag for oracle grading (M-F)"
```

---

### Task 4: `roll_forward(freeze_world=...)`

**Files:**
- Modify: `fleet/agent/oracle.py:56-69` (`roll_forward` signature + body)
- Test: `tests/test_oracle.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_oracle.py`:

```python
def test_roll_forward_freeze_world_freezes_demand_and_is_pure():
    from config.settings import load_settings
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    from fleet.agent.oracle import roll_forward
    from fleet.contracts.state import Decision, DecisionAction, DecisionEngine

    settings = load_settings({})
    state = build_sample_state()
    sim = WorldSimulator(settings)
    pending_before = state.total_orders_pending()
    probe = Decision(id="P", timestamp=state.clock, event_id=None,
                     action=DecisionAction.REPRIORITIZE,
                     engine=DecisionEngine.RULE_BASED, description="p")
    rolled = roll_forward(sim, state, probe, horizon=10, freeze_world=True)
    # original untouched (purity); clone advanced; no new demand injected
    assert state.sim_tick == 0
    assert rolled.sim_tick == 10
    assert rolled.total_orders_pending() <= pending_before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_oracle.py::test_roll_forward_freeze_world_freezes_demand_and_is_pure -q`
Expected: FAIL with `TypeError: roll_forward() got an unexpected keyword argument 'freeze_world'`

- [ ] **Step 3: Add the parameter**

In `fleet/agent/oracle.py`, change the `roll_forward` signature and body:

```python
def roll_forward(simulator, state: WorldState, decision: Decision, horizon: int,
                 resolve: Optional[Callable[[WorldState], None]] = None,
                 freeze_world: bool = False) -> WorldState:
    """Clone (simulator, state, decision) TOGETHER — so the seeded rng is cloned
    with the world and every candidate sees an identical future — then apply the
    decision, optionally re-solve (resolve callback, only for RESOLVE_ACTIONS),
    and tick `horizon` times. When `freeze_world` is set, the cloned simulator runs
    in advance-only mode (no new demand/restock/shortage/weather) so the rolled-out
    cost reflects the decision, not unrelated order churn. Inputs are never
    mutated."""
    sim_c, state_c, dec_c = copy.deepcopy((simulator, state, decision))
    if freeze_world:
        sim_c.advance_only = True
    Dispatcher().apply(state_c, dec_c)
    if resolve is not None and dec_c.action in RESOLVE_ACTIONS:
        resolve(state_c)
    for _ in range(horizon):
        sim_c.tick(state_c)
    return state_c
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_oracle.py -q`
Expected: all PASS (existing oracle tests still pass; `freeze_world` defaults to False).

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/oracle.py tests/test_oracle.py
git commit -m "feat(oracle): roll_forward freeze_world (advance-only grading, M-F)"
```

---

### Task 5: Consequential injuries + disrupted grading

**Files:**
- Modify: `fleet/agent/dataset.py` (imports; add `_critical_edges`, `_DISRUPT_SURGE_UNITS`, `make_disrupted_example`, `grade_disrupted`, `iter_disrupted_examples`)
- Test: `tests/test_dataset.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dataset.py`:

```python
def test_make_disrupted_example_blocks_critical_edges():
    from dataclasses import replace
    from config.settings import load_settings
    from fleet.factory import build_components
    from fleet.agent.dataset import make_disrupted_example, DATASET_EVENT_SPECS
    from fleet.contracts.state import EdgeStatus, EventType

    settings = replace(load_settings({}), enable_travel_time=True)
    optimizer = build_components(settings).optimizer
    spec = next(s for s in DATASET_EVENT_SPECS if s[0] == EventType.TRAFFIC)
    sim, state, event = make_disrupted_example(42, spec, settings, optimizer)
    # the event targets a customer, and that customer's direct depot edges are cut
    assert event.target in state.customers
    blocked = [e for e in state.road_graph.edges.values()
               if e.from_node == "DEPOT" and e.to_node == event.target]
    assert blocked and all(e.status == EdgeStatus.BLOCKED for e in blocked)


def test_grade_disrupted_distinguishes_actions_for_an_edge_event():
    from dataclasses import replace
    from config.settings import load_settings
    from fleet.factory import build_components
    from fleet.agent.dataset import make_disrupted_example, grade_disrupted, DATASET_EVENT_SPECS
    from fleet.contracts.state import EventType

    settings = replace(load_settings({}), enable_travel_time=True,
                       oracle_horizon_ticks=72)
    optimizer = build_components(settings).optimizer
    spec = next(s for s in DATASET_EVENT_SPECS if s[0] == EventType.TRAFFIC)
    sim, state, event = make_disrupted_example(7, spec, settings, optimizer)
    full = grade_disrupted(sim, state, event, settings, optimizer)
    costs = [c for _a, c, _d in full]
    # the candidates no longer grade identically — there is a real best/worst gap
    assert max(costs) - min(costs) > 0.0
    # sorted ascending by cost (oracle's best first)
    assert costs == sorted(costs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dataset.py::test_make_disrupted_example_blocks_critical_edges tests/test_dataset.py::test_grade_disrupted_distinguishes_actions_for_an_edge_event -q`
Expected: FAIL with `ImportError: cannot import name 'make_disrupted_example'`

- [ ] **Step 3: Implement the disrupted factory + grader**

In `fleet/agent/dataset.py`, extend the contracts import to add `EdgeStatus` and `VehicleStatus`:

```python
from fleet.contracts.state import (
    WorldState, Event, DecisionAction, Decision, DecisionEngine,
    EventType, EventSeverity, EdgeStatus, VehicleStatus,
)
```

Extend the planner import to add `reroute`:

```python
from fleet.routing.planner import plan_routes, reroute
```

Add this block (place it after `make_example` / `iter_examples`, before the reasoning helpers):

```python
_DISRUPT_SURGE_UNITS = 500   # M-F: surge magnitude that makes a disruption bite


def _critical_edges(state: WorldState, customer_id: str,
                    depot_id: str = "DEPOT"):
    """Direct depot->customer access edges (including any parallel '#2'). Blocking
    all of these forces a costly detour or isolates the customer, so reroute vs
    defer become genuinely different choices."""
    return [eid for eid, e in state.road_graph.edges.items()
            if e.from_node == depot_id and e.to_node == customer_id]


def _first_pending_customer(state: WorldState) -> str:
    for cid in sorted(state.customers):
        if sum(state.customers[cid].orders.values()) > 0:
            return cid
    return sorted(state.customers)[0]


def make_disrupted_example(seed: int, spec, settings, optimizer,
                           warmup_ticks: int = 6):
    """M-F: like make_example, but actually INJURES the world so the disruption
    poses a real choice. Needs settings.enable_travel_time for edge/vehicle signal.
    Returns (simulator, state, event). Deterministic given the inputs."""
    s = replace(settings, seed=seed)
    state = build_sample_state()
    sim = WorldSimulator(s)
    plan_routes(state, optimizer)
    for _ in range(warmup_ticks):
        sim.tick(state)
    event_type, severity, kind = spec

    if kind == "edge":
        target = _first_pending_customer(state)
        new_status = (EdgeStatus.FLOODED if event_type == EventType.FLOODED_AREA
                      else EdgeStatus.BLOCKED)
        for eid in _critical_edges(state, target):
            edge = state.road_graph.get_edge(eid)
            edge.status = new_status
            if new_status == EdgeStatus.FLOODED:
                edge.flood_level = 2.0
        event = sim.inject_event(state, event_type, target, severity)

    elif kind == "customer":
        target = sorted(state.customers)[0]
        cust = state.customers[target]
        sku = (sorted(state.depot.inventory) or ["SKU001"])[0]
        cust.orders[sku] = cust.orders.get(sku, 0) + _DISRUPT_SURGE_UNITS
        if event_type == EventType.URGENT_ORDER:
            cust.time_window.start = state.clock
        event = sim.inject_event(state, event_type, target, severity)

    elif kind == "sku":
        target = sorted(state.depot.inventory)[0]
        cust = state.customers[sorted(state.customers)[0]]
        cust.orders[target] = cust.orders.get(target, 0) + _DISRUPT_SURGE_UNITS
        pending = sum(c.orders.get(target, 0) for c in state.customers.values())
        state.depot.inventory[target] = max(0, pending // 2)   # real shortage
        event = sim.inject_event(state, event_type, target, severity)

    elif kind == "vehicle":
        target = sorted(state.vehicles)[0]
        state.vehicles[target].status = VehicleStatus.BROKEN
        sku = (sorted(state.depot.inventory) or ["SKU001"])[0]
        for c in state.customers.values():            # pressure the remaining fleet
            c.orders[sku] = c.orders.get(sku, 0) + _DISRUPT_SURGE_UNITS
        event = sim.inject_event(state, event_type, target, severity)

    else:
        raise ValueError(f"unknown target kind: {kind}")

    return sim, state, event


def grade_disrupted(simulator, state: WorldState, event: Event, settings,
                    optimizer):
    """M-F oracle grading: roll each candidate forward with travel-time movement,
    exogenous demand frozen, and a re-solve on RESOLVE_ACTIONS — so realized cost
    reflects the decision. Returns [(action, realized_cost, realized_delay_min)]
    sorted by (cost, action.value)."""
    weights = _Weights(settings)
    horizon = settings.oracle_horizon_ticks

    def resolve(st: WorldState) -> None:
        reroute(st, optimizer)

    results = []
    for a in candidate_actions(event.event_type):
        probe = Decision(
            id="ORACLE_PROBE", timestamp=state.clock, event_id=event.id, action=a,
            engine=DecisionEngine.RULE_BASED, description=f"oracle probe {a.value}")
        rolled = roll_forward(simulator, state, probe, horizon, resolve,
                              freeze_world=True)
        results.append((a, realized_cost(rolled, weights),
                        realized_delay_minutes(rolled)))
    results.sort(key=lambda t: (t[1], t[0].value))
    return results


def iter_disrupted_examples(settings, n_seeds: int, optimizer,
                            warmup_ticks: int = 6):
    """Yield (seed, (simulator, state, event)) over seeds x DATASET_EVENT_SPECS,
    using the consequential (injured) world."""
    for seed in range(settings.seed, settings.seed + n_seeds):
        for spec in DATASET_EVENT_SPECS:
            yield seed, make_disrupted_example(seed, spec, settings, optimizer,
                                               warmup_ticks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dataset.py -q`
Expected: all PASS (the two new tests plus the existing M-B dataset tests, which are untouched).

- [ ] **Step 5: Commit**

```bash
git add fleet/agent/dataset.py tests/test_dataset.py
git commit -m "feat(dataset): consequential injuries + grade_disrupted (M-F)"
```

---

### Task 6: `gen_dataset --consequential`

**Files:**
- Modify: `scripts/gen_dataset.py` (import; `build_dataset(consequential=...)`; `main` flag + travel-time/horizon)
- Test: `tests/test_gen_dataset.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_gen_dataset.py`:

```python
def test_consequential_dataset_multi_class_coverage(tmp_path):
    from dataclasses import replace
    from config.settings import load_settings
    from scripts.gen_dataset import build_dataset

    settings = replace(load_settings({}), enable_travel_time=True,
                       oracle_horizon_ticks=72)
    report = build_dataset(settings, n_seeds=3, out_dir=str(tmp_path),
                           consequential=True)
    # the dataset is no longer single-class: several event types are informative
    assert len(report["event_types"]) >= 4
    assert report["informative_fraction"] > 0.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_gen_dataset.py::test_consequential_dataset_multi_class_coverage -q`
Expected: FAIL with `TypeError: build_dataset() got an unexpected keyword argument 'consequential'`

- [ ] **Step 3: Wire the consequential path**

In `scripts/gen_dataset.py`, add `iter_disrupted_examples` and `grade_disrupted` to the dataset import, and add `from dataclasses import replace` at the top:

```python
from dataclasses import replace
...
from fleet.agent.dataset import (
    iter_examples, grade_full, is_informative, build_record, batch_reasoning,
    split_by_seed, default_batch_submit, build_preference_record, templated_reasoning,
    iter_disrupted_examples, grade_disrupted,
)
```

Change `build_dataset` to accept and use `consequential`:

```python
def build_dataset(settings, n_seeds, out_dir, holdout_frac=0.2, use_teacher=False,
                  dpo=False, consequential=False):
    """Generate the dataset and write {train,test}.jsonl (and prefs.jsonl when dpo)
    under out_dir. When consequential, injure the world per event type and grade
    with travel-time + frozen demand so all event types can be informative.
    Returns a report dict (counts, informative fraction, coverage)."""
    optimizer = build_components(settings).optimizer

    graded = []          # (seed, state, event, full)
    n_total = 0
    examples_iter = (iter_disrupted_examples(settings, n_seeds, optimizer)
                     if consequential
                     else iter_examples(settings, n_seeds, optimizer))
    for seed, (sim, state, event) in examples_iter:
        n_total += 1
        full = (grade_disrupted(sim, state, event, settings, optimizer)
                if consequential
                else grade_full(sim, state, event, settings))
        scored = [(a, c) for a, c, _d in full]
        if is_informative(scored, settings.oracle_min_gap):
            graded.append((seed, state, event, full))
```

(Leave the rest of `build_dataset` — examples assembly, reasoning, records, split, write, coverage, return — exactly as it is.)

Update `main` to add the flag and force travel-time + an adequate horizon when consequential:

```python
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=200)
    p.add_argument("--out", default="data/sovereign-brain")
    p.add_argument("--holdout-frac", type=float, default=0.2)
    p.add_argument("--use-teacher", action="store_true",
                   help="label reasoning via Sonnet 4.6 Batch (needs ANTHROPIC_API_KEY)")
    p.add_argument("--dpo", action="store_true",
                   help="also emit prefs.jsonl (oracle best/worst preference pairs)")
    p.add_argument("--consequential", action="store_true",
                   help="M-F: injure the world per event type + travel-time grading "
                        "(multi-class dataset). Forces enable_travel_time and a "
                        "grading horizon of at least 60 ticks.")
    args = p.parse_args()

    settings = load_settings()
    if args.consequential:
        horizon = max(settings.oracle_horizon_ticks, 60)
        settings = replace(settings, enable_travel_time=True,
                           oracle_horizon_ticks=horizon)

    report = build_dataset(settings, args.seeds, args.out, args.holdout_frac,
                           args.use_teacher, args.dpo, args.consequential)
    print(json.dumps(report, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_gen_dataset.py -q`
Expected: all PASS.

> **Tuning note (only if Step 4's coverage assertion fails):** the mechanism is correct; coverage depends on injury magnitude vs. fleet/window slack. In `fleet/agent/dataset.py` raise `_DISRUPT_SURGE_UNITS` (e.g. 500 → 1000) and/or run with a longer horizon (`oracle_horizon_ticks=96`). Re-run Step 4. `vehicle_breakdown` is the weakest type (the 3-vehicle fleet absorbs one loss); if it never becomes informative, that is acceptable per the spec — the served brain falls back to the rule action for it.

- [ ] **Step 5: Commit**

```bash
git add scripts/gen_dataset.py tests/test_gen_dataset.py
git commit -m "feat(gen_dataset): --consequential multi-class path (M-F)"
```

---

### Task 7: Full-suite regression + smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the full SBv2 suite**

Run: `python -m pytest tests/test_config.py tests/test_travel_time.py tests/test_oracle.py tests/test_dataset.py tests/test_gen_dataset.py tests/test_movement.py tests/test_loop.py tests/test_simulator.py tests/test_eval_online.py tests/test_factory.py -q`
Expected: all PASS — default-off flags leave existing behavior unchanged.

- [ ] **Step 2: Run the entire test suite**

Run: `python -m pytest -q`
Expected: all PASS, no threshold edits.

- [ ] **Step 3: $0 multi-class smoke (no GPU/network)**

Run: `python -m scripts.gen_dataset --consequential --seeds 4 --out data/_mf_smoke`
Expected: JSON report with `event_types` covering ≥4 distinct types and `informative_fraction` > 0.2.

- [ ] **Step 4: Clean up the smoke artifacts**

Run: `rm -rf data/_mf_smoke`

- [ ] **Step 5: Commit (if anything changed) — otherwise skip**

No code change in this task; nothing to commit unless the tuning note was applied.

---

## Self-Review

**1. Spec coverage:**
- §3.1 travel-time movement → Task 2. ✓
- §3.2 per-event injuries (`make_disrupted_example`, `_critical_edges`) → Task 5. ✓
- §3.3 grading wired (freeze + re-solve + horizon) → `roll_forward(freeze_world)` Task 4, `grade_disrupted` Task 5, horizon forced in `main` Task 6. ✓
- §3.4 settings/factory additions → `enable_travel_time` Task 1, `advance_only` Task 3, `freeze_world` Task 4. ✓
- §4 config gating / suite safety → regression runs in Tasks 2 & 7. ✓
- §5 coverage expectation → Task 6 assertion `>= 4` + tuning note. ✓
- §6 downstream → out of scope for this plan (runbook re-runs M-D/M-E on the new data); no task needed here. ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases". The Task 6 tuning note names exact knobs (`_DISRUPT_SURGE_UNITS`, `oracle_horizon_ticks`) and is operational guidance, not a code placeholder. ✓

**3. Type/name consistency:** `enable_travel_time` (settings) read via `getattr(self.settings, "enable_travel_time", False)`; `advance_only` (sim attr) set by `roll_forward(freeze_world=True)`; `_advance`/`_advance_vehicles_travel_time`/`_advance_vehicles` dispatch; `make_disrupted_example`/`grade_disrupted`/`iter_disrupted_examples` used identically in dataset and gen_dataset; `roll_forward(simulator, state, decision, horizon, resolve=None, freeze_world=False)` matches the `grade_disrupted` call `roll_forward(simulator, state, probe, horizon, resolve, freeze_world=True)`. ✓
