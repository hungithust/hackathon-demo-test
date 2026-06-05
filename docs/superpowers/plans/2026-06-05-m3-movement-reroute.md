# M3 (part 3) — Vehicle Movement + Reroute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make trucks actually *move* along the routes the solver produced — visiting stops on schedule, delivering (consuming depot inventory and clearing customer orders), and returning to the depot — and make the system *re-solve* when the road network changes (an edge floods or is blocked). This closes the demand → plan → deliver loop and turns a REROUTE decision into a real route change.

**Architecture:** Movement is **schedule-driven**, not physics-driven: each tick the simulator walks every vehicle's route in `state.plan` and marks any stop whose `planned_arrival <= clock` as visited (`actual_arrival/departure`, move `pos`, advance `current_stop_index`), delivering on arrival. When all stops are visited and the shift end has passed, the vehicle returns to AT_DEPOT. Re-solving reuses Plan 5's `plan_routes` (renamed concept `reroute`) — because the time matrix is rebuilt from the *current* graph, a blocked/flooded edge automatically reshapes the routes. The loop plans once up front and re-plans whenever an approved REROUTE decision fires.

**Tech Stack:** Python 3.10+, Google OR-Tools (already added in Plan 5), dataclasses, pytest. Same repo/venv/branch — no new dependency.

---

## Context

- Continues branch **`feat/base-project`** (plans 1–5 executed & green; 86 passing).
- Builds on: M2 `WorldSimulator` (demand/restock/shortage living world, no movement yet), Plan 4 `build_time_matrix`/`build_routing_problem` (flood/blocked/parallel-edge aware), Plan 5 `CpuSolver` + `plan_routes` (writes `VehicleRoute`s into `state.plan`).
- **Scope completes M3:** vehicles move + deliver, and the world re-solves on disruption. This is the milestone where the headless loop visibly "does something useful."
- **No new external dependency.** Movement and reroute are pure-Python on top of existing modules.

**Key facts from the current code (verified on disk):**
- `Stop(customer_id, sequence, planned_arrival, planned_departure, actual_arrival=None, actual_departure=None, load_after_stop=0.0)`.
- `VehicleRoute(vehicle_id, stops, total_distance, total_time, start_time, end_time)`.
- `Vehicle` has `pos: Location`, `status: VehicleStatus`, `current_stop_index: int = -1`, `veh_type`, `wade_capability`. `VehicleStatus`: AT_DEPOT, IN_TRANSIT, ON_ROUTE, BROKEN, MAINTENANCE.
- `CustomerProfile` has `location: Location` and `orders: Dict[str, int]` (sku→qty).
- `Depot` has `location: Location` and `inventory: Dict[str, int]`.
- `WorldState.plan: Dict[vehicle_id, VehicleRoute]`, `state.customers`/`state.vehicles` keyed by id, `state.total_orders_pending()`.
- `WorldSimulator.tick()` already calls `_generate_demand → _maybe_restock → _update_shortage_events`. We append `_advance_vehicles` as the final step.
- `RoadEdge` has `status: EdgeStatus`, `flood_level`, `traffic_factor`, `effective_time`, `is_passable(wade)`. `EdgeStatus`: OPEN, CONGESTED, BLOCKED, FLOODED. Graph parallel edges via `out_edges`/`edges_between`/`get_edge`.
- `RuleBasedEngine` maps FLOODED_AREA/TRAFFIC → `DecisionAction.REROUTE`; `should_auto_approve` auto-approves REROUTE when `added_delay_min <= threshold`.

**Modeling decisions (documented in code):**
- Movement is **schedule-based** (visit a stop once `clock >= planned_arrival`). No interpolation along edges in M3 — keeps it deterministic and matrix-consistent; smooth animation can come later in the UI milestone.
- A vehicle in `BROKEN` or `MAINTENANCE` is **skipped** (its route is frozen; reallocation is a later milestone).
- `_deliver` consumes depot inventory **per delivered sku** down to a floor of 0 and **clears that customer's orders** (a delivery satisfies the outstanding order). Delivery quantity = the customer's current order qty for each sku at arrival time.
- Reroute = rebuild the matrix from the live graph + re-solve. The matrix already excludes impassable edges, so blocking/flooding an edge changes the routes with no special-casing.
- Disruption is injected via `WorldSimulator.disrupt_edge(...)`, which mutates the graph edge **and** emits an Event (so the detector/agent react and the loop's REROUTE path is exercised end-to-end).

**Changes:** `fleet/simulator/engine.py` (add movement + `disrupt_edge`), `fleet/routing/planner.py` (add `reroute`), `fleet/loop.py` (initial plan + reroute on approved REROUTE), new `tests/test_movement.py`, new `tests/test_reroute.py`, and an update to `tests/test_loop.py::test_loop_world_comes_alive_over_many_ticks`.

Environment reminder (Windows / PowerShell): activate venv `.\.venv\Scripts\Activate.ps1`; run tests `pytest -v`; commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Only `git add` the files named in each task — do NOT touch `Guide.md`, `problem.txt`, `docs/PROBLEM_STATEMENT.md`.

---

### Task 1: Vehicle movement + delivery in the simulator

**Files:**
- Modify: `fleet/simulator/engine.py`
- Test: new `tests/test_movement.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_movement.py`:
```python
from datetime import timedelta

from fleet.scenarios import build_sample_state
from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import Stop, VehicleRoute, VehicleStatus
from config.settings import load_settings


def _make_route(state, vid, customer_id):
    """One-stop route arriving at the very next tick boundary."""
    cust = state.customers[customer_id]
    arrival = state.clock + timedelta(minutes=load_settings().tick_minutes)
    stop = Stop(customer_id=customer_id, sequence=1,
                planned_arrival=arrival,
                planned_departure=arrival + timedelta(minutes=10),
                load_after_stop=0.0)
    state.plan[vid] = VehicleRoute(vehicle_id=vid, stops=[stop],
                                   start_time=arrival,
                                   end_time=stop.planned_departure)


def test_vehicle_visits_stop_on_schedule():
    s = build_sample_state()
    cust_id = "C001"
    s.customers[cust_id].orders = {"SKUX": 40}
    s.depot.inventory["SKUX"] = 100
    _make_route(s, "V001", cust_id)
    sim = WorldSimulator(load_settings())

    sim.tick(s)   # clock advances to the planned arrival

    stop = s.plan["V001"].stops[0]
    assert stop.actual_arrival is not None
    v = s.vehicles["V001"]
    assert v.current_stop_index == 1
    assert v.pos == s.customers[cust_id].location
    assert v.status == VehicleStatus.ON_ROUTE


def test_delivery_consumes_inventory_and_clears_orders():
    s = build_sample_state()
    s.customers["C001"].orders = {"SKUX": 40}
    s.depot.inventory["SKUX"] = 100
    sim = WorldSimulator(load_settings())

    sim._deliver(s, s.vehicles["V001"], "C001")

    assert s.depot.inventory["SKUX"] == 60
    assert s.customers["C001"].orders == {}


def test_inventory_never_goes_negative():
    s = build_sample_state()
    s.customers["C001"].orders = {"SKUX": 40}
    s.depot.inventory["SKUX"] = 10          # not enough stock
    sim = WorldSimulator(load_settings())

    sim._deliver(s, s.vehicles["V001"], "C001")

    assert s.depot.inventory["SKUX"] == 0
    assert s.customers["C001"].orders == {}


def test_vehicles_without_plan_are_untouched():
    s = build_sample_state()           # sample world has no plan
    sim = WorldSimulator(load_settings())
    before = {vid: v.status for vid, v in s.vehicles.items()}
    sim.tick(s)
    assert {vid: v.status for vid, v in s.vehicles.items()} == before
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_movement.py -v`
Expected: FAIL — `AttributeError: 'WorldSimulator' object has no attribute '_deliver'` (and the movement test fails because `tick` does not move vehicles yet).

- [ ] **Step 3: Implement movement + delivery**

In `fleet/simulator/engine.py`, extend the import:
```python
from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, VehicleStatus,
)
```

Add `_advance_vehicles` as the final step of `tick`:
```python
    def tick(self, state: WorldState) -> None:
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1
        if self._restock_batch is None:
            self._restock_batch = dict(state.depot.inventory)
        self._generate_demand(state)
        self._maybe_restock(state)
        self._update_shortage_events(state)
        self._advance_vehicles(state)
```

Append these methods to `WorldSimulator`:
```python
    def _advance_vehicles(self, state: WorldState) -> None:
        """Schedule-driven movement: visit every stop whose planned arrival has
        passed, delivering on arrival; return to depot once the shift is over."""
        for vid, route in state.plan.items():
            vehicle = state.vehicles.get(vid)
            if vehicle is None or vehicle.status in (
                    VehicleStatus.BROKEN, VehicleStatus.MAINTENANCE):
                continue
            for stop in route.stops:
                if stop.actual_arrival is None and stop.planned_arrival <= state.clock:
                    stop.actual_arrival = state.clock
                    stop.actual_departure = state.clock
                    cust = state.customers.get(stop.customer_id)
                    if cust is not None:
                        vehicle.pos = cust.location
                    vehicle.current_stop_index = stop.sequence
                    vehicle.status = VehicleStatus.ON_ROUTE
                    self._deliver(state, vehicle, stop.customer_id)
            all_visited = route.stops and all(
                s.actual_arrival is not None for s in route.stops)
            shift_done = route.end_time is None or state.clock >= route.end_time
            if all_visited and shift_done:
                vehicle.status = VehicleStatus.AT_DEPOT
                vehicle.pos = state.depot.location
                vehicle.current_stop_index = -1

    def _deliver(self, state: WorldState, vehicle: "Vehicle",
                 customer_id: str) -> None:
        """Satisfy a customer's outstanding order: draw down depot stock (floored
        at 0) and clear the order."""
        cust = state.customers.get(customer_id)
        if cust is None:
            return
        for sku, qty in cust.orders.items():
            on_hand = state.depot.inventory.get(sku, 0)
            state.depot.inventory[sku] = max(0, on_hand - qty)
        cust.orders = {}
```

Add `Vehicle` to the import (it's referenced only in a type hint, so the string annotation `"Vehicle"` keeps it optional — but import it for clarity):
```python
from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, VehicleStatus, Vehicle,
)
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_movement.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite (catch regressions early)**

Run: `pytest -v`
Expected: the sample world has no `state.plan`, so `_advance_vehicles` is a no-op for `test_simulator`/`test_loop_advances_clock`; all prior tests still green. **Exception:** `test_loop_world_comes_alive_over_many_ticks` is fixed in Task 2 — if it fails *here* it's only because the loop doesn't plan yet (no plan ⇒ no delivery ⇒ that test is unaffected at this point; it should still pass). If any *other* test regresses, stop and investigate.

- [ ] **Step 6: Commit**

```
git add fleet/simulator/engine.py tests/test_movement.py
git commit -m "feat(simulator): schedule-driven vehicle movement + delivery

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Loop plans routes up front, then vehicles move

**Files:**
- Modify: `fleet/loop.py`
- Test: `tests/test_loop.py` (update `test_loop_world_comes_alive_over_many_ticks`, add `test_loop_plans_and_moves_vehicles`)

- [ ] **Step 1: Write/adjust the failing tests**

In `tests/test_loop.py`, **replace** `test_loop_world_comes_alive_over_many_ticks`'s body assertion (net-pending no longer grows monotonically once deliveries happen) and add a new test:
```python
def test_loop_world_comes_alive_over_many_ticks():
    s = build_sample_state()
    settings = load_settings(env={"TICK_MINUTES": "30",
                                  "RESTOCK_INTERVAL_MIN": "100000"})
    comps = build_components(settings)
    run_loop(s, comps, n_ticks=20, settings=settings, logger=_silent)
    assert s.sim_tick == 20
    # the loop planned routes and at least one stop was actually visited
    assert s.plan
    assert any(st.actual_arrival is not None
               for r in s.plan.values() for st in r.stops)


def test_loop_plans_and_moves_vehicles():
    s = build_sample_state()
    # seed a concrete order so there is something to plan + deliver
    s.customers["C001"].orders = {"SKUX": 20}
    s.depot.inventory["SKUX"] = 200
    settings = load_settings(env={"TICK_MINUTES": "15"})
    comps = build_components(settings)
    run_loop(s, comps, n_ticks=8, settings=settings, logger=_silent)
    assert s.plan                                   # initial plan was built
    visited = [st for r in s.plan.values() for st in r.stops
               if st.actual_arrival is not None]
    assert visited                                  # at least one delivery happened
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_loop.py -v`
Expected: FAIL — `assert s.plan` is false because `run_loop` never plans.

- [ ] **Step 3: Add initial planning to the loop**

In `fleet/loop.py`, add the import:
```python
from fleet.routing.planner import plan_routes
```
At the top of `run_loop`, before the tick loop:
```python
def run_loop(state: WorldState, components: Components, n_ticks: int,
             settings, logger: Callable[..., None] = print) -> WorldState:
    if not state.plan and state.total_orders_pending() > 0:
        plan_routes(state, components.optimizer)
    for _ in range(n_ticks):
        ...
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_loop.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add fleet/loop.py tests/test_loop.py
git commit -m "feat(loop): plan routes up front so vehicles move and deliver

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `reroute()` + `disrupt_edge()`

**Files:**
- Modify: `fleet/routing/planner.py` (add `reroute`)
- Modify: `fleet/simulator/engine.py` (add `disrupt_edge`)
- Test: new `tests/test_reroute.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reroute.py`:
```python
from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.routing.planner import reroute
from fleet.routing.matrix import build_time_matrix
from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import EdgeStatus, EventType
from config.settings import load_settings


def test_disrupt_edge_changes_graph_and_emits_event():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    evt = sim.disrupt_edge(s, "DEPOT->C001", EdgeStatus.BLOCKED)
    assert s.road_graph.get_edge("DEPOT->C001").status == EdgeStatus.BLOCKED
    assert evt.event_type == EventType.TRAFFIC or evt.event_type == EventType.FLOODED_AREA
    assert evt in s.events


def test_blocking_edge_reroutes_depot_to_c001_via_detour():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    locations = ["DEPOT", "C001", "C002", "C003", "C004"]
    direct = build_time_matrix(s.road_graph, locations, wade_capability=0.3)
    i, j = locations.index("DEPOT"), locations.index("C001")
    before = direct[i][j]

    sim.disrupt_edge(s, "DEPOT->C001", EdgeStatus.BLOCKED)

    after = build_time_matrix(s.road_graph, locations, wade_capability=0.3)
    assert after[i][j] > before     # forced onto a longer detour (or unreachable)


def test_reroute_returns_dropped_list_and_keeps_plan_consistent():
    s = build_sample_state()
    s.customers["C001"].orders = {"SKUX": 20}
    s.depot.inventory["SKUX"] = 200
    comps = build_components(load_settings())
    dropped = reroute(s, comps.optimizer)
    assert isinstance(dropped, list)
    assert s.plan                                   # a fresh plan was written
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_reroute.py -v`
Expected: FAIL — `ImportError: cannot import name 'reroute'` and `AttributeError: ... 'disrupt_edge'`.

- [ ] **Step 3: Implement**

In `fleet/routing/planner.py`, add (reroute is a fresh full re-solve against the *current* graph — the matrix already reflects edge changes, so no diff logic is needed):
```python
def reroute(state: WorldState, optimizer: RouteOptimizer,
            depot_id: str = "DEPOT") -> List[str]:
    """Re-solve from scratch against the current road graph. Because the time
    matrix is rebuilt from live edge statuses, a blocked/flooded edge is already
    excluded and the routes adapt automatically. Returns dropped customer ids."""
    return plan_routes(state, optimizer, depot_id)
```

In `fleet/simulator/engine.py`, add `EdgeStatus` to the import and a `disrupt_edge` method:
```python
from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, VehicleStatus, Vehicle,
    EdgeStatus,
)
```
```python
    def disrupt_edge(self, state: WorldState, edge_id: str,
                     new_status: EdgeStatus, flood_level: float = 0.0,
                     traffic_factor: float = 1.0) -> Event:
        """Mutate a road edge (block/flood/congest) and emit the matching event so
        the detector + agent react and the loop's reroute path is exercised."""
        edge = state.road_graph.get_edge(edge_id)
        if edge is None:
            raise KeyError(f"no such edge: {edge_id}")
        edge.status = new_status
        if flood_level:
            edge.flood_level = flood_level
        if traffic_factor != 1.0:
            edge.traffic_factor = traffic_factor
        evt_type = (EventType.FLOODED_AREA
                    if new_status == EdgeStatus.FLOODED
                    else EventType.TRAFFIC)
        severity = (EventSeverity.CRITICAL
                    if new_status == EdgeStatus.BLOCKED
                    else EventSeverity.MEDIUM)
        evt = Event(
            id=self._new_event_id(), event_type=evt_type, target=edge_id,
            severity=severity, started_at=state.clock,
            description=f"{new_status.value} on {edge_id}",
        )
        state.events.append(evt)
        return evt
```
> Note: if `EventSeverity.MEDIUM` is not a member, use the existing moderate level (e.g. `LOW`); check `fleet/contracts/state.py` for the `EventSeverity` enum and pick the closest non-critical value.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_reroute.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add fleet/routing/planner.py fleet/simulator/engine.py tests/test_reroute.py
git commit -m "feat(routing): reroute() re-solve + simulator.disrupt_edge() with event

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Loop re-solves on an approved REROUTE

**Files:**
- Modify: `fleet/loop.py`
- Test: `tests/test_loop.py` (add `test_loop_reroutes_on_edge_disruption`)

- [ ] **Step 1: Write the failing test**

In `tests/test_loop.py`, add (top-of-file import already has `DecisionAction`):
```python
from fleet.contracts.state import EdgeStatus


def test_loop_reroutes_on_edge_disruption():
    s = build_sample_state()
    s.customers["C001"].orders = {"SKUX": 20}
    s.depot.inventory["SKUX"] = 200
    settings = load_settings()
    comps = build_components(settings)
    # flood the depot->C001 link: FLOODED_AREA -> RuleBasedEngine REROUTE -> auto-approve
    comps.simulator.disrupt_edge(s, "DEPOT->C001", EdgeStatus.FLOODED,
                                 flood_level=0.9)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    reroutes = [d for d in s.decisions
                if d.action == DecisionAction.REROUTE
                and d.approval_status == ApprovalStatus.APPROVED]
    assert reroutes                       # the loop produced + approved a reroute
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_loop.py::test_loop_reroutes_on_edge_disruption -v`
Expected: it may already *find* the approved REROUTE decision (Plan 5 wiring) but the loop does not yet *act* on it. To make the test meaningfully drive the new behavior, assert the reroute is executed: add to the test
```python
    assert any(d.executed_at is not None for d in reroutes)
```
Expected then: FAIL until the loop calls `reroute` (executed_at set by dispatcher) — confirm what `dispatcher.apply` sets; if it already stamps `executed_at`, keep the assertion; otherwise the failing signal is that `reroute` is never invoked (add a spy or assert plan changed). Choose the assertion that actually fails before Step 3 — do not proceed on a green test.

- [ ] **Step 3: Wire reroute into the loop**

In `fleet/loop.py`, import:
```python
from fleet.contracts.state import WorldState, ApprovalStatus, DecisionAction
from fleet.routing.planner import plan_routes, reroute
```
Inside the tick loop, track whether any approved decision asks to reroute, and re-solve once after processing the tick's decisions:
```python
        rerouted = False
        for d in decisions:
            state.decisions.append(d)
            severity = severity_by_event.get(d.event_id)
            if should_auto_approve(d, severity, settings):
                d.approval_status = ApprovalStatus.APPROVED
                d.approved_by = "auto"
                d.approved_at = state.clock
                components.dispatcher.apply(state, d)
                if d.action == DecisionAction.REROUTE:
                    rerouted = True
                verdict = "AUTO-APPLIED"
            else:
                verdict = "QUEUED(approval)"
            logger(...)

        if rerouted and state.total_orders_pending() > 0:
            reroute(state, components.optimizer)

        logger(...)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_loop.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + smoke run**

Run: `pytest -v` (expect all green — prior count plus the new movement/reroute tests).
Run: `python -m fleet.loop` (should run clean; with the demo TRAFFIC injection you should see REROUTE auto-applied lines).

- [ ] **Step 6: Commit**

```
git add fleet/loop.py tests/test_loop.py
git commit -m "feat(loop): re-solve routes when an approved REROUTE fires

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification checklist (end of plan)

- [ ] `pytest -v` fully green.
- [ ] Vehicles in `state.plan` advance through stops on schedule; `actual_arrival`/`pos`/`current_stop_index` update; vehicle returns AT_DEPOT after shift end.
- [ ] Delivery draws down depot inventory (floored at 0) and clears the customer's orders.
- [ ] `disrupt_edge` mutates the graph edge and emits an event; the recomputed time matrix reflects the change.
- [ ] An approved REROUTE in the loop triggers a fresh `reroute` re-solve.
- [ ] `python -m fleet.loop` runs clean.
- [ ] Only the files named in each task were committed (no `Guide.md`/`problem.txt`/`docs/PROBLEM_STATEMENT.md`).

**Completes M3.** Next milestone: **M4 — CuOptAdapter behind the `RouteOptimizer` interface** (GPU solver plugs in beside `CpuSolver`, selected by `config/settings.py`).
