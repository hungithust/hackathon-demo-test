# Order Lifecycle Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the simulated orders to the control room so an admin can dispatch them per-order (waves) or all at once, watch their progress with explicit order↔vehicle linkage, and review the day as a replayable event→decision→event log.

**Architecture:** Pure-derivation lifecycle (inbox / in-progress / delivered) computed from existing `state.plan` + `customers.orders` — no new `WorldState` schema fields. Backend adds customer/vehicle filters to the routing problem, wave dispatch that merges into the plan without disturbing busy vehicles, gating so the world no longer auto-plans, and an in-memory timeline of view-model snapshots for replay. Frontend adds a tabbed left column (Events | Inbox | Progress) and a full-screen Day-Log overlay that re-renders recorded snapshots through the existing `DispatchMap`.

**Tech Stack:** Python 3 / FastAPI / pytest (backend); in-browser React 18 + Babel-standalone (no build step), components registered on `window` (frontend).

**Spec:** `docs/superpowers/specs/2026-06-12-order-lifecycle-control-design.md`

---

## File Structure

**Backend (TDD with pytest):**
- `fleet/routing/matrix.py` — add `customer_ids` / `vehicle_ids` filters to `build_routing_problem`.
- `fleet/routing/planner.py` — thread `customer_ids` through `_build_plan` / `preview_reroute` / `reroute`; add `plan_wave`.
- `fleet/loop.py` — add `auto_plan` flag; scope full re-solves to dispatched customers when gated.
- `fleet/ui/controller.py` — gating in `step`; `dispatch_all` / `dispatch_orders`; `inbox` + `orders_in_progress` in `snapshot`; `timeline` recording + `daylog`.
- `fleet/ui/server.py` — `POST /api/dispatch`, `GET /api/daylog`.
- `tests/test_order_lifecycle.py` — new test module for everything above.

**Frontend (manual verification — no JSX test harness in repo):**
- `fleet/ui/web/api.jsx` — `dispatch` / `daylog` client methods; normalize `inbox` + `orders_in_progress`.
- `fleet/ui/web/panels.jsx` — `InboxPanel`, `ProgressPanel`, `OrderDetail` components.
- `fleet/ui/web/daylog.jsx` (new) — full-screen Day-Log overlay; registered in `index.html`.
- `fleet/ui/web/app.jsx` — left-column tabs, `selectedOrder` state, Day-Log button + wiring.
- `fleet/ui/web/index.html` — load `daylog.jsx`.

**Phase A** = Tasks 1–8 (gating + waves + inbox + progress + linkage). **Phase B** = Tasks 9–11 (day-log). Phase A is independently shippable; stop there for a checkpoint if desired.

---

## PHASE A — Dispatch gating, waves, inbox, progress

### Task 1: Customer/vehicle filters on `build_routing_problem`

**Files:**
- Modify: `fleet/routing/matrix.py:252-263`, `:274-276`
- Test: `tests/test_order_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_order_lifecycle.py`:

```python
from fleet.scenarios import build_sample_state
from fleet.routing.matrix import build_routing_problem


def test_build_problem_filters_customers():
    state = build_sample_state()
    prob = build_routing_problem(state, customer_ids={"C001"})
    task_ids = {t.customer_id for t in prob.tasks}
    assert task_ids == {"C001"}


def test_build_problem_filters_vehicles():
    state = build_sample_state()
    only = next(iter(state.vehicles))
    prob = build_routing_problem(state, vehicle_ids={only})
    assert {v.id for v in prob.fleet} == {only}


def test_build_problem_no_filter_is_unchanged():
    state = build_sample_state()
    prob = build_routing_problem(state)
    pending = {c for c in state.customers if sum(state.customers[c].orders.values()) > 0}
    assert {t.customer_id for t in prob.tasks} == pending
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_lifecycle.py -v`
Expected: FAIL — `build_routing_problem() got an unexpected keyword argument 'customer_ids'`.

- [ ] **Step 3: Add the filter parameters**

In `fleet/routing/matrix.py`, change the signature and the two collection lines:

```python
def build_routing_problem(state: WorldState,
                          depot_id: str = "DEPOT",
                          customer_ids=None,
                          vehicle_ids=None) -> RoutingProblem:
```

Replace the `pending = [...]` list comprehension (currently `:262-263`) with:

```python
    pending = [cid for cid in sorted(state.customers)
               if sum(state.customers[cid].orders.values()) > 0
               and (customer_ids is None or cid in customer_ids)]
```

Replace the `available = [...]` comprehension (currently `:275-276`) with:

```python
    available = [v for v in state.vehicles.values()
                 if v.status not in (VehicleStatus.BROKEN, VehicleStatus.MAINTENANCE)
                 and (vehicle_ids is None or v.id in vehicle_ids)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_lifecycle.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the existing matrix suite to confirm no regression**

Run: `python -m pytest tests/test_matrix.py tests/test_routing_problem.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add fleet/routing/matrix.py tests/test_order_lifecycle.py
git commit -m "feat(routing): customer/vehicle filters on build_routing_problem"
```

---

### Task 2: Thread `customer_ids` through planner re-solves

**Files:**
- Modify: `fleet/routing/planner.py:20-22` (`_build_plan`), `:72-75` (`preview_reroute`), `:150-154` (`reroute`)
- Test: `tests/test_order_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_lifecycle.py`:

```python
from fleet.routing.planner import reroute, _build_plan
from fleet.factory import build_components
from config.settings import load_settings


def _optimizer():
    return build_components(load_settings()).optimizer


def test_build_plan_respects_customer_filter():
    state = build_sample_state()
    _dropped, plan = _build_plan(state, _optimizer(), customer_ids={"C001"})
    planned = {s.customer_id for vr in plan.values() for s in vr.stops}
    assert planned <= {"C001"}


def test_reroute_respects_customer_filter():
    state = build_sample_state()
    reroute(state, _optimizer(), customer_ids={"C001", "C002"})
    planned = {s.customer_id for vr in state.plan.values() for s in vr.stops}
    assert planned <= {"C001", "C002"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_lifecycle.py -k filter -v`
Expected: FAIL — `_build_plan() got an unexpected keyword argument 'customer_ids'`.

- [ ] **Step 3: Thread the parameter through all three functions**

In `fleet/routing/planner.py`, change `_build_plan` (`:20-22`):

```python
def _build_plan(state: WorldState, optimizer: RouteOptimizer,
                depot_id: str = "DEPOT",
                customer_ids=None) -> Tuple[List[str], Dict[str, VehicleRoute]]:
    problem = build_routing_problem(state, depot_id, customer_ids=customer_ids)
```

Change `preview_reroute` (`:72-75`):

```python
def preview_reroute(state: WorldState, optimizer: RouteOptimizer,
                    depot_id: str = "DEPOT",
                    customer_ids=None) -> Tuple[List[str], Dict[str, VehicleRoute]]:
    old_plan = {vid: route for vid, route in state.plan.items()}
    dropped, new_plan = _build_plan(state, optimizer, depot_id, customer_ids=customer_ids)
```

Change `reroute` (`:150-154`):

```python
def reroute(state: WorldState, optimizer: RouteOptimizer,
            depot_id: str = "DEPOT", customer_ids=None) -> List[str]:
    dropped, new_plan = preview_reroute(state, optimizer, depot_id, customer_ids=customer_ids)
    state.plan = new_plan
    return dropped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_lifecycle.py -k filter -v`
Expected: PASS.

- [ ] **Step 5: Run planner/reroute suites**

Run: `python -m pytest tests/test_planner.py tests/test_reroute.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add fleet/routing/planner.py tests/test_order_lifecycle.py
git commit -m "feat(routing): thread customer_ids filter through reroute/_build_plan"
```

---

### Task 3: `plan_wave` — dispatch selected customers to idle vehicles, merge

**Files:**
- Modify: `fleet/routing/planner.py` (add `plan_wave` near `plan_routes`, after `:57`)
- Test: `tests/test_order_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_lifecycle.py`:

```python
from fleet.routing.planner import plan_wave, plan_routes
from fleet.contracts.state import VehicleStatus


def test_plan_wave_only_plans_selected_customers():
    state = build_sample_state()
    plan_wave(state, _optimizer(), {"C001"})
    planned = {s.customer_id for vr in state.plan.values() for s in vr.stops}
    assert planned == {"C001"}


def test_plan_wave_merges_without_touching_busy_vehicles():
    state = build_sample_state()
    # Wave 1: dispatch C001 -> some vehicle gets a route.
    plan_wave(state, _optimizer(), {"C001"})
    busy_vid = next(vid for vid, vr in state.plan.items() if vr.stops)
    # Simulate the vehicle being out on the road (busy, not idle).
    state.vehicles[busy_vid].status = VehicleStatus.ON_ROUTE
    busy_route_before = state.plan[busy_vid]
    # Wave 2: dispatch C002 -> must use a DIFFERENT (idle) vehicle.
    plan_wave(state, _optimizer(), {"C002"})
    assert state.plan[busy_vid] is busy_route_before, "busy vehicle's route was replaced"
    planned = {s.customer_id for vr in state.plan.values() for s in vr.stops}
    assert {"C001", "C002"} <= planned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_lifecycle.py -k wave -v`
Expected: FAIL — `cannot import name 'plan_wave'`.

- [ ] **Step 3a: Extract `_build_plan_from_solution` to avoid duplicating Stop-construction**

In `fleet/routing/planner.py`, refactor `_build_plan` (`:20-51`). Move the body that turns a `solution` into a plan dict into a new helper, and have `_build_plan` call it. The result is:

```python
def _build_plan_from_solution(state: WorldState, solution,
                              depot_id: str = "DEPOT") -> Tuple[List[str], Dict[str, VehicleRoute]]:
    new_plan = {}
    for vid, solved in solution.routes.items():
        if not solved:
            continue
        stops = [
            Stop(customer_id=ss.customer_id, sequence=k,
                 planned_arrival=ss.arrival, planned_departure=ss.departure,
                 load_after_stop=ss.load_after,
                 demand_kg=float(sum(state.customers[ss.customer_id].orders.values()))
                 if ss.customer_id in state.customers else 0.0)
            for k, ss in enumerate(solved, start=1)
        ]
        vehicle = state.get_vehicle(vid)
        wade = float(vehicle.wade_capability) if vehicle else 0.3
        home = vehicle.home_depot if (vehicle and vehicle.home_depot in state.all_depots()) else depot_id

        first_leg_min = shortest_times_from(state.road_graph, home, wade).get(stops[0].customer_id, 0.0)
        last_leg_min = shortest_times_from(state.road_graph, stops[-1].customer_id, wade).get(home, 0.0)
        start_time = stops[0].planned_arrival - __import__("datetime").timedelta(minutes=first_leg_min)
        new_plan[vid] = VehicleRoute(
            vehicle_id=vid, stops=stops,
            total_time=solution.metrics.get("total_time_min", 0.0),
            start_time=start_time,
            end_time=stops[-1].planned_departure + __import__("datetime").timedelta(minutes=last_leg_min),
        )
    return solution.dropped, new_plan


def _build_plan(state: WorldState, optimizer: RouteOptimizer,
                depot_id: str = "DEPOT",
                customer_ids=None) -> Tuple[List[str], Dict[str, VehicleRoute]]:
    problem = build_routing_problem(state, depot_id, customer_ids=customer_ids)
    solution = optimizer.solve(problem)
    return _build_plan_from_solution(state, solution, depot_id)
```

(This supersedes the `_build_plan` edit made in Task 2 Step 3 — same `customer_ids` behavior, now delegating to the shared helper.)

- [ ] **Step 3b: Implement `_idle_vehicle_ids` and `plan_wave`**

Add directly after `plan_routes` (`:57`):

```python
def _idle_vehicle_ids(state: WorldState) -> list:
    """Vehicles available to take a new wave: parked at a depot with no route, or
    one whose every stop is already delivered (finished a prior wave)."""
    from fleet.contracts.state import VehicleStatus
    out = []
    for v in state.vehicles.values():
        if v.status != VehicleStatus.AT_DEPOT:
            continue
        vr = state.plan.get(v.id)
        if vr is None or not vr.stops or all(s.actual_arrival is not None for s in vr.stops):
            out.append(v.id)
    return out


def plan_wave(state: WorldState, optimizer: RouteOptimizer,
              customer_ids, depot_id: str = "DEPOT") -> List[str]:
    """Plan a dispatch wave for the given inbox customers using only idle vehicles,
    merging the result into state.plan so vehicles already running are untouched."""
    from fleet.routing.matrix import build_routing_problem
    idle = _idle_vehicle_ids(state)
    if not idle:
        return list(customer_ids)          # nothing free -> all deferred
    problem = build_routing_problem(state, depot_id,
                                    customer_ids=set(customer_ids),
                                    vehicle_ids=set(idle))
    solution = optimizer.solve(problem)
    _dropped, new_plan = _build_plan_from_solution(state, solution, depot_id)
    state.plan.update(new_plan)              # merge: busy vehicles' routes untouched
    return solution.dropped
```

`build_routing_problem` is already imported at the top of `planner.py` (used by `_build_plan`); the local import is defensive and harmless.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_lifecycle.py -k wave -v`
Expected: PASS.

- [ ] **Step 5: Full planner regression**

Run: `python -m pytest tests/test_planner.py tests/test_reroute.py tests/test_order_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add fleet/routing/planner.py tests/test_order_lifecycle.py
git commit -m "feat(routing): plan_wave merges a dispatch wave onto idle vehicles"
```

---

### Task 4: Gate `run_loop` auto-plan; scope full re-solves when gated

**Files:**
- Modify: `fleet/loop.py:165-168`, `:318-321`
- Test: `tests/test_order_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_lifecycle.py`:

```python
from fleet.loop import run_loop
from fleet.factory import build_components as _bc


def test_run_loop_no_auto_plan_leaves_world_undispatched():
    state = build_sample_state()
    settings = load_settings()
    run_loop(state, _bc(settings), n_ticks=2, settings=settings,
             logger=lambda *a, **k: None, auto_plan=False)
    assert state.plan == {}, "gated loop must not auto-plan the world"


def test_run_loop_default_still_auto_plans():
    state = build_sample_state()
    settings = load_settings()
    run_loop(state, _bc(settings), n_ticks=1, settings=settings,
             logger=lambda *a, **k: None)
    assert state.plan, "headless default must keep auto-planning"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_lifecycle.py -k auto_plan -v`
Expected: FAIL — `run_loop() got an unexpected keyword argument 'auto_plan'`.

- [ ] **Step 3: Add the flag and gate the auto-plan + scope the re-solve**

In `fleet/loop.py`, change the signature (`:165-166`):

```python
def run_loop(state: WorldState, components: Components, n_ticks: int,
             settings, logger: Callable[..., None] = print,
             auto_plan: bool = True) -> WorldState:
    if auto_plan and not state.plan and state.total_orders_pending() > 0:
        plan_routes(state, components.optimizer)
```

Change the `needs_resolve` block (`:318-321`) so a gated re-solve only touches already-dispatched customers (never pulls inbox customers in):

```python
        if needs_resolve and state.total_orders_pending() > 0:
            before = plan_total_minutes(state)
            if auto_plan:
                reroute(state, components.optimizer)
            else:
                dispatched = {s.customer_id for vr in state.plan.values() for s in vr.stops}
                reroute(state, components.optimizer, customer_ids=dispatched)
            added = max(0.0, plan_total_minutes(state) - before)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_lifecycle.py -k auto_plan -v`
Expected: PASS.

- [ ] **Step 5: Run the loop suite**

Run: `python -m pytest tests/test_loop.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add fleet/loop.py tests/test_order_lifecycle.py
git commit -m "feat(loop): auto_plan gate + scope gated re-solve to dispatched customers"
```

---

### Task 5: Controller gating + `dispatch_all` / `dispatch_orders`

**Files:**
- Modify: `fleet/ui/controller.py:171-175` (`step`), `:680-681` (approve fallback); add `dispatch_all` / `dispatch_orders` methods
- Test: `tests/test_order_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_lifecycle.py`:

```python
from fleet.ui.controller import SimulationController


def test_controller_does_not_auto_dispatch_on_step():
    c = SimulationController()
    c.step(2)
    assert c.state.plan == {}, "stepping must not dispatch anything by itself"


def test_dispatch_all_matches_full_plan_routes():
    c = SimulationController()
    c.dispatch_all()
    planned = {s.customer_id for vr in c.state.plan.values() for s in vr.stops}
    pending = {cid for cid in c.state.customers
               if sum(c.state.customers[cid].orders.values()) > 0}
    assert planned == pending


def test_dispatch_orders_is_a_wave():
    c = SimulationController()
    c.dispatch_orders(["C001"])
    planned = {s.customer_id for vr in c.state.plan.values() for s in vr.stops}
    assert planned == {"C001"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_lifecycle.py -k "dispatch or auto_dispatch" -v`
Expected: FAIL — `test_controller_does_not_auto_dispatch_on_step` fails (plan is non-empty) and `dispatch_all` is undefined.

- [ ] **Step 3: Gate `step` and add the dispatch methods**

In `fleet/ui/controller.py`, change `step` (`:171-175`) to pass `auto_plan=False`:

```python
    def step(self, n_ticks: int = 1):
        from fleet.loop import run_loop
        run_loop(self.state, self.components, max(1, int(n_ticks)),
                 settings=self.settings, logger=_silent, auto_plan=False)
        return self
```

Add these methods right after `step` (before `_route_nodes`):

```python
    # ----- admin-driven dispatch -----
    def dispatch_all(self):
        """Plan every inbox order (= today's Play-everything behavior)."""
        from fleet.routing.planner import plan_routes
        plan_routes(self.state, self.components.optimizer)
        return self

    def dispatch_orders(self, customer_ids):
        """Dispatch a wave for the selected inbox customers onto idle vehicles."""
        from fleet.routing.planner import plan_wave
        ids = [cid for cid in customer_ids if cid in self.state.customers]
        if ids:
            plan_wave(self.state, self.components.optimizer, set(ids))
        return self
```

In the approve fallback re-solve (`:680-681`), scope to dispatched customers so approving a non-reroute resolve action never pulls inbox customers in. Replace the `else:` branch:

```python
            else:
                # Fallback: full re-solve, scoped to already-dispatched customers
                dispatched = {s.customer_id for vr in self.state.plan.values() for s in vr.stops}
                reroute(self.state, self.components.optimizer, customer_ids=dispatched)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_lifecycle.py -k "dispatch or auto_dispatch" -v`
Expected: PASS.

- [ ] **Step 5: Run the controller suite (note the behavior change)**

Run: `python -m pytest tests/test_ui_controller.py -v`
Expected: Most PASS. If `test_step_advances_the_world` or `test_end_to_end_step_then_approve_flow` assumed an auto-built plan, update them to call `c.dispatch_all()` before stepping. Make that edit if needed and re-run until PASS.

- [ ] **Step 6: Commit**

```bash
git add fleet/ui/controller.py tests/test_order_lifecycle.py tests/test_ui_controller.py
git commit -m "feat(ui): gate stepping; add dispatch_all / dispatch_orders waves"
```

---

### Task 6: `inbox` + `orders_in_progress` in `snapshot()`

**Files:**
- Modify: `fleet/ui/controller.py` (`snapshot`, add two derivation helpers)
- Test: `tests/test_order_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_lifecycle.py`:

```python
def test_inbox_holds_undispatched_orders():
    c = SimulationController()
    snap = c.snapshot()
    inbox_ids = {r["customer_id"] for r in snap["inbox"]}
    pending = {cid for cid in c.state.customers
               if sum(c.state.customers[cid].orders.values()) > 0}
    assert inbox_ids == pending
    assert snap["orders_in_progress"] == []


def test_dispatch_moves_order_from_inbox_to_progress():
    c = SimulationController()
    c.dispatch_orders(["C001"])
    snap = c.snapshot()
    assert "C001" not in {r["customer_id"] for r in snap["inbox"]}
    prog = {o["customer_id"]: o for o in snap["orders_in_progress"]}
    assert "C001" in prog
    assert prog["C001"]["vehicle_id"]          # order<->vehicle link is present
    assert prog["C001"]["status"] in ("queued", "en_route", "delivered")


def test_snapshot_with_inbox_is_json_safe():
    import json
    c = SimulationController()
    c.dispatch_orders(["C001"])
    c.step(1)
    json.dumps(c.snapshot())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_lifecycle.py -k "inbox or progress" -v`
Expected: FAIL — `KeyError: 'inbox'`.

- [ ] **Step 3: Add derivation helpers and wire them into `snapshot`**

In `fleet/ui/controller.py`, add these helpers just before `def snapshot` (`:448`):

```python
    def _dispatched_customer_ids(self) -> set:
        return {s.customer_id for vr in self.state.plan.values() for s in vr.stops}

    def _inbox(self):
        dispatched = self._dispatched_customer_ids()
        rows = []
        for c in self.state.customers.values():
            if c.id in dispatched:
                continue
            total = sum(c.orders.values())
            if total <= 0:
                continue
            rows.append({
                "customer_id": c.id,
                "name": c.location.name,
                "type": c.type,
                "priority": c.priority,
                "orders": dict(c.orders),
                "total_qty": total,
                "demand_kg": float(total),
                "tw_start": c.time_window.start.isoformat(),
                "tw_end": c.time_window.end.isoformat(),
                "sla_deadline": c.sla_deadline.isoformat() if c.sla_deadline else None,
            })
        rows.sort(key=lambda r: (r["priority"], r["customer_id"]))
        return rows

    def _orders_in_progress(self):
        out = []
        for vid, vr in self.state.plan.items():
            stops = sorted(vr.stops, key=lambda s: s.sequence)
            total = len(stops)
            nxt = next((s for s in stops if s.actual_arrival is None), None)
            for s in stops:
                c = self.state.customers.get(s.customer_id)
                if s.actual_arrival is not None:
                    status = "delivered"
                elif nxt is not None and s.sequence == nxt.sequence:
                    status = "en_route"
                else:
                    status = "queued"
                out.append({
                    "customer_id": s.customer_id,
                    "name": c.location.name if c else s.customer_id,
                    "vehicle_id": vid,
                    "sequence": s.sequence,
                    "stops_total": total,
                    "status": status,
                    "priority": c.priority if c else 4,
                    "demand_kg": float(s.demand_kg),
                    "planned_arrival": s.planned_arrival.isoformat() if s.planned_arrival else None,
                    "actual_arrival": s.actual_arrival.isoformat() if s.actual_arrival else None,
                })
        return out
```

In `snapshot`, add two keys to the returned dict (e.g. right after `"pending_orders": s.total_orders_pending(),` at `:458`):

```python
            "inbox": self._inbox(),
            "orders_in_progress": self._orders_in_progress(),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_lifecycle.py -k "inbox or progress or json_safe" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fleet/ui/controller.py tests/test_order_lifecycle.py
git commit -m "feat(ui): derive inbox + orders_in_progress in snapshot"
```

---

### Task 7: `POST /api/dispatch` endpoint

**Files:**
- Modify: `fleet/ui/server.py` (add `DispatchBody` + endpoint near `:135`)
- Test: `tests/test_order_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_lifecycle.py`:

```python
from fleet.ui import server as S


def test_dispatch_endpoint_all():
    S._overrides = {}
    S._ctrl = S.SimulationController()
    snap = S.post_dispatch(S.DispatchBody(all=True))
    assert snap["orders_in_progress"], "deliver-all should populate progress"


def test_dispatch_endpoint_selected():
    S._overrides = {}
    S._ctrl = S.SimulationController()
    snap = S.post_dispatch(S.DispatchBody(customer_ids=["C001"]))
    assert "C001" not in {r["customer_id"] for r in snap["inbox"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_lifecycle.py -k endpoint -v`
Expected: FAIL — `module 'fleet.ui.server' has no attribute 'DispatchBody'`.

- [ ] **Step 3: Add the request model and endpoint**

In `fleet/ui/server.py`, add after the `StepBody` class (`:109-110`):

```python
class DispatchBody(BaseModel):
    customer_ids: list = []
    all: bool = False
```

Add the endpoint after `post_step` (`:133`):

```python
@app.post("/api/dispatch")
def post_dispatch(body: DispatchBody):
    with _lock:
        c = _controller()
        if body.all:
            c.dispatch_all()
        else:
            c.dispatch_orders(body.customer_ids)
        return c.snapshot()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_lifecycle.py -k endpoint -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fleet/ui/server.py tests/test_order_lifecycle.py
git commit -m "feat(server): POST /api/dispatch (all + selected waves)"
```

---

### Task 8: Frontend — Inbox + Progress tabs, order↔vehicle linkage

No JSX test harness exists; verify by running the server and observing the UI.

**Files:**
- Modify: `fleet/ui/web/api.jsx` (normalize + `dispatch`)
- Modify: `fleet/ui/web/panels.jsx` (`InboxPanel`, `ProgressPanel`, `OrderDetail`)
- Modify: `fleet/ui/web/app.jsx` (left-column tabs, `selectedOrder`)

- [ ] **Step 1: Carry the new fields through `normalize` + `emptyState` and add the client method**

In `fleet/ui/web/api.jsx`, inside `normalize` add (after `routes: snap.routes || [],`):

```javascript
    inbox: snap.inbox || [],
    ordersInProgress: snap.orders_in_progress || [],
```

In `emptyState` add `inbox: [], ordersInProgress: [],` to the returned object.

Add to the `Api` object (after `reject:`):

```javascript
  dispatch: async (body) => normalize(await jpost("/api/dispatch", body)),
```

- [ ] **Step 2: Add `InboxPanel`, `ProgressPanel`, `OrderDetail` to `panels.jsx`**

Append before the final `Object.assign(window, {...})` line:

```javascript
// ---------------- INBOX (incoming orders) ----------------
function InboxPanel({ state, onDispatch }) {
  const [sel, setSel] = React.useState(() => new Set());
  const toggle = (id) => setSel((s) => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
  });
  const rows = state.inbox;
  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-head">
        <Icon name="inbox" size={15} style={{ color: "var(--accent)" }}/>
        <h2>Đơn tới</h2>
        <span className="count">{rows.length}</span>
      </div>
      <div className="panel-body pad">
        {rows.length === 0 ? (
          <div className="empty"><div className="e-ico"><Icon name="check" size={22}/></div>
            <div className="e-title">Hết đơn chờ</div>
            <div className="e-sub">Mọi đơn đã được điều phối.</div></div>
        ) : rows.map((r) => (
          <label key={r.customer_id} className={"order-row" + (sel.has(r.customer_id) ? " sel" : "")}
            style={{ display: "flex", gap: 8, alignItems: "center", padding: "8px 6px", borderBottom: "1px solid var(--border)", cursor: "pointer" }}>
            <input type="checkbox" checked={sel.has(r.customer_id)} onChange={() => toggle(r.customer_id)}/>
            <span className="mono" style={{ color: "#60a5fa" }}>{r.customer_id}</span>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</span>
            <span className="tag">P{r.priority}</span>
            <span className="mono" style={{ color: "var(--text-3)" }}>{r.total_qty}</span>
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, padding: 10, borderTop: "1px solid var(--border)" }}>
        <button className="btn" disabled={sel.size === 0}
          onClick={() => { onDispatch({ customer_ids: [...sel] }); setSel(new Set()); }}>
          Giao đã chọn ({sel.size})
        </button>
        <button className="btn primary" style={{ marginLeft: "auto" }}
          onClick={() => onDispatch({ all: true })}>Giao tất cả</button>
      </div>
    </div>
  );
}

const ORDER_STATUS = {
  queued:    { label: "Đang chờ xe", color: "#94a3b8" },
  en_route:  { label: "Đang giao",   color: "#f59e0b" },
  delivered: { label: "Đã giao",     color: "#22c55e" },
};

// ---------------- ORDER PROGRESS ----------------
function ProgressPanel({ state, selectedVeh, selectedOrder, onSelectOrder }) {
  let rows = state.ordersInProgress;
  if (selectedVeh) rows = rows.filter((o) => o.vehicle_id === selectedVeh);  // vehicle -> its orders
  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-head">
        <Icon name="truck" size={15} style={{ color: "var(--text-2)" }}/>
        <h2>Tiến trình{selectedVeh ? " · " + selectedVeh : ""}</h2>
        <span className="count">{rows.length}</span>
      </div>
      <div className="panel-body">
        {rows.length === 0 ? (
          <div className="empty"><div className="e-ico"><Icon name="inbox" size={22}/></div>
            <div className="e-title">Chưa giao đơn nào</div>
            <div className="e-sub">Chọn đơn ở tab “Đơn tới” rồi bấm giao.</div></div>
        ) : rows.map((o) => {
          const st = ORDER_STATUS[o.status];
          const isSel = selectedOrder === o.customer_id;
          return (
            <div key={o.vehicle_id + ":" + o.customer_id}
              className={"event-row" + (isSel ? " sel" : "")}
              style={{ "--ev-accent": st.color }}
              onClick={() => onSelectOrder(isSel ? null : o.customer_id)}>
              <div className="ev-main">
                <div className="ev-top">
                  <span className="ev-type">{o.customer_id} · {o.name}</span>
                  <span className="tag" style={{ color: st.color }}>{st.label}</span>
                </div>
                <div className="ev-meta">
                  <span className="mono" style={{ color: "#60a5fa" }}>{o.vehicle_id}</span>
                  <span className="mono">dừng {o.sequence}/{o.stops_total}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {selectedOrder && <OrderDetail state={state} cid={selectedOrder}/>}
    </div>
  );
}

// ---------------- ORDER DETAIL ----------------
function OrderDetail({ state, cid }) {
  const o = state.ordersInProgress.find((x) => x.customer_id === cid);
  if (!o) return null;
  const st = ORDER_STATUS[o.status];
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: 10, fontSize: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>{o.customer_id} · {o.name}</div>
      <div className="tt-row"><span>Xe phụ trách</span><span className="mono" style={{ color: "#60a5fa" }}>{o.vehicle_id}</span></div>
      <div className="tt-row"><span>Trạng thái</span><span style={{ color: st.color }}>{st.label}</span></div>
      <div className="tt-row"><span>Thứ tự dừng</span><span className="mono">{o.sequence}/{o.stops_total}</span></div>
      <div className="tt-row"><span>Khối lượng</span><span className="mono">{Math.round(o.demand_kg)} kg</span></div>
      <div className="tt-row"><span>Dự kiến đến</span><span className="mono">{o.planned_arrival ? fmtClock(o.planned_arrival) : "—"}</span></div>
      <div className="tt-row"><span>Thực tế đến</span><span className="mono">{o.actual_arrival ? fmtClock(o.actual_arrival) : "—"}</span></div>
    </div>
  );
}
```

Add `InboxPanel, ProgressPanel, OrderDetail` to the `Object.assign(window, {...})` list at the end of the file.

- [ ] **Step 3: Wire the tabbed left column + `selectedOrder` in `app.jsx`**

In `App`, add state (after `const [selectedEvent, ...]`):

```javascript
  const [leftTab, setLeftTab] = React.useState("events"); // events | inbox | progress
  const [selectedOrder, setSelectedOrder] = React.useState(null);
  const onDispatch = (body) => guard(() => Api.dispatch(body));
```

Replace the left column block (`<div className="col"><EventList .../></div>`, `:106-108`) with:

```javascript
        <div className="col">
          <div className="toggle-tabs" style={{ margin: "0 0 8px" }}>
            <button className={leftTab === "events" ? "on" : ""} onClick={() => setLeftTab("events")}>Sự kiện</button>
            <button className={leftTab === "inbox" ? "on" : ""} onClick={() => setLeftTab("inbox")}>Đơn tới <span className="count">{state.inbox.length}</span></button>
            <button className={leftTab === "progress" ? "on" : ""} onClick={() => setLeftTab("progress")}>Tiến trình</button>
          </div>
          {leftTab === "events" && <EventList state={state} selected={selectedEvent} onSelect={setSelectedEvent}/>}
          {leftTab === "inbox" && <InboxPanel state={state} onDispatch={onDispatch}/>}
          {leftTab === "progress" && <ProgressPanel state={state} selectedVeh={selectedVeh} selectedOrder={selectedOrder} onSelectOrder={setSelectedOrder}/>}
        </div>
```

Wire the order→map highlight: pass `selectedOrder` into `DispatchMap` so it can pulse that customer marker. Update the map invocation (`:112`):

```javascript
            <DispatchMap state={state} speed={speed} selectedVeh={selectedVeh} onSelectVeh={setSelectedVeh} selectedEvent={selectedEvent} selectedOrder={selectedOrder}/>
```

In `fleet/ui/web/map.jsx`, accept the prop in the `DispatchMap` signature (`:23`) — add `selectedOrder` to the destructured props — and where customer markers are rendered, add a highlight class when `c.id === selectedOrder` (e.g. append `+ (c.id === selectedOrder ? " sel" : "")` to that marker's className). Locate the customer-marker `.map(...)` in `map.jsx` and add the conditional class.

- [ ] **Step 4: Bump the `?v=` cache-busting query for edited files in `index.html`**

In `fleet/ui/web/index.html` (`:387-391`), increment the version suffix on `api.jsx`, `map.jsx`, `panels.jsx`, and `app.jsx` (e.g. `?v=7` → `?v=8`) so the browser reloads them.

- [ ] **Step 5: Manual verification**

Run: `python -m fleet.ui.server`
Open `http://127.0.0.1:8686`. Verify:
- Left column shows three tabs; "Đơn tới" lists all customers with a count, none in "Tiến trình".
- Tick a couple of orders → "Giao đã chọn (2)" → they leave the inbox and appear in "Tiến trình"; vehicles get routes on the map.
- "Giao tất cả" dispatches everything (same as pressing Play used to).
- Press Play: orders move queued → en_route → delivered.
- Click an order in "Tiến trình" → detail card shows the assigned vehicle; the customer marker is highlighted on the map. Click a vehicle in the Fleet strip → "Tiến trình" filters to that vehicle's orders (order↔vehicle linkage both directions).

- [ ] **Step 6: Commit**

```bash
git add fleet/ui/web/api.jsx fleet/ui/web/panels.jsx fleet/ui/web/app.jsx fleet/ui/web/map.jsx fleet/ui/web/index.html
git commit -m "feat(ui): inbox + progress tabs with order<->vehicle linkage"
```

**PHASE A complete — shippable. Checkpoint here if you want to demo before building the Day-Log.**

---

## PHASE B — Daily Log replay

### Task 9: Timeline recording in the controller

**Files:**
- Modify: `fleet/ui/controller.py` (`__init__`, `step`, `dispatch_*`; add `_record_timeline`)
- Test: `tests/test_order_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_lifecycle.py`:

```python
from fleet.contracts.state import EventType, EventSeverity


def test_timeline_records_event_then_decision():
    c = SimulationController()
    c.dispatch_all()
    c.components.simulator.inject_event(
        c.state, EventType.VEHICLE_BREAKDOWN, "V001", EventSeverity.CRITICAL)
    c.step(2)
    assert c.timeline, "timeline should record at least one change snapshot"
    # snapshots are trimmed of static geometry to bound memory
    assert "routes" not in c.timeline[-1]["snapshot"]
    # every entry carries a clock + a re-renderable view-model
    assert all("clock" in e and "snapshot" in e for e in c.timeline)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_lifecycle.py -k timeline -v`
Expected: FAIL — `'SimulationController' object has no attribute 'timeline'`.

- [ ] **Step 3: Add timeline state + recording**

In `fleet/ui/controller.py` `__init__`, after `self.components = build_components(self.settings)`:

```python
        self.timeline = []
        self._last_log_sig = None
```

Add the recorder method (near `step`):

```python
    def _record_timeline(self):
        """Append a view-model snapshot whenever the set of active events or the
        decision statuses changed since the last record. The map geometry (`routes`)
        is static, so it is dropped here and re-applied client-side to bound memory."""
        sig = (
            tuple(sorted(e.id for e in self.state.get_active_events())),
            tuple(sorted((d.id, d.approval_status.value) for d in self.state.decisions)),
        )
        if sig == self._last_log_sig:
            return
        self._last_log_sig = sig
        snap = self.snapshot()
        snap.pop("routes", None)
        self.timeline.append({
            "seq": len(self.timeline),
            "clock": self.state.clock.isoformat(),
            "sim_tick": self.state.sim_tick,
            "snapshot": snap,
        })
```

Call `self._record_timeline()` at the end of `step`, `dispatch_all`, and `dispatch_orders` (before each `return self`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_lifecycle.py -k timeline -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fleet/ui/controller.py tests/test_order_lifecycle.py
git commit -m "feat(ui): record change-boundary timeline snapshots for replay"
```

---

### Task 10: `daylog()` + `GET /api/daylog`

**Files:**
- Modify: `fleet/ui/controller.py` (add `daylog`), `fleet/ui/server.py` (add endpoint)
- Test: `tests/test_order_lifecycle.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_order_lifecycle.py`:

```python
def test_daylog_chains_events_and_decisions():
    import json
    c = SimulationController()
    c.dispatch_all()
    c.components.simulator.inject_event(
        c.state, EventType.VEHICLE_BREAKDOWN, "V001", EventSeverity.CRITICAL)
    c.step(2)
    log = c.daylog()
    assert log["timeline"] and log["events"] and log["decisions"]
    # decisions link back to events for the event->decision->event chain
    assert any(d["event_id"] for d in log["decisions"])
    json.dumps(log)   # JSON-safe


def test_daylog_endpoint():
    S._overrides = {}
    S._ctrl = S.SimulationController()
    S._ctrl.dispatch_all()
    S.post_step(S.StepBody(n=1))
    log = S.get_daylog()
    assert "timeline" in log and "events" in log and "decisions" in log
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_order_lifecycle.py -k daylog -v`
Expected: FAIL — `'SimulationController' object has no attribute 'daylog'`.

- [ ] **Step 3: Add `daylog()` to the controller**

In `fleet/ui/controller.py`, add after `_record_timeline`:

```python
    def daylog(self):
        """Full-day review payload: recorded map snapshots + the authoritative
        event/decision records (with timestamps + event_id links) the UI renders
        as an event -> decision -> event chain."""
        s = self.state
        all_events = list(s.events_archive) + list(s.events)
        return {
            "timeline": self.timeline,
            "events": [
                {"id": e.id, "event_type": e.event_type.value, "target": e.target,
                 "severity": e.severity.value, "started_at": e.started_at.isoformat(),
                 "ended_at": e.ended_at.isoformat() if e.ended_at else None,
                 "description": e.description}
                for e in all_events
            ],
            "decisions": [
                {"id": d.id, "action": d.action.value, "engine": d.engine.value,
                 "event_id": d.event_id, "timestamp": d.timestamp.isoformat(),
                 "status": d.approval_status.value, "approved_by": d.approved_by,
                 "approved_at": d.approved_at.isoformat() if d.approved_at else None,
                 "added_delay_min": d.impact_estimate.get("added_delay_min", 0.0),
                 "reasoning": d.reasoning, "description": d.description}
                for d in s.decisions
            ],
        }
```

In `fleet/ui/server.py`, add after `get_snapshot` (`:124`):

```python
@app.get("/api/daylog")
def get_daylog():
    with _lock:
        return _controller().daylog()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_order_lifecycle.py -k daylog -v`
Expected: PASS.

- [ ] **Step 5: Full backend suite**

Run: `python -m pytest tests/test_order_lifecycle.py tests/test_ui_controller.py tests/test_loop.py tests/test_settings_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add fleet/ui/controller.py fleet/ui/server.py tests/test_order_lifecycle.py
git commit -m "feat(server): GET /api/daylog (timeline + event/decision chain)"
```

---

### Task 11: Frontend — Day-Log full-screen overlay

No JSX test harness; verify by running the server.

**Files:**
- Create: `fleet/ui/web/daylog.jsx`
- Modify: `fleet/ui/web/api.jsx` (add `daylog` fetch), `fleet/ui/web/index.html` (load script), `fleet/ui/web/app.jsx` (header button + overlay)

- [ ] **Step 1: Add the API method**

In `fleet/ui/web/api.jsx`, add to the `Api` object:

```javascript
  daylog: async () => jget("/api/daylog"),
```

- [ ] **Step 2: Create the overlay component**

Create `fleet/ui/web/daylog.jsx`:

```javascript
// daylog.jsx — full-screen day review. Left: event->decision->event chain built
// from authoritative event/decision records. Right: the recorded view-model
// snapshot at that moment, re-rendered through the live DispatchMap (static).

function DayLogOverlay({ open, onClose }) {
  const [log, setLog] = React.useState(null);
  const [staticRoutes, setStaticRoutes] = React.useState([]);
  const [sel, setSel] = React.useState(0);

  React.useEffect(() => {
    if (!open) return;
    Api.daylog().then(setLog).catch((e) => console.error(e));
    Api.snapshot().then((s) => setStaticRoutes(s.routes)).catch(() => {});
  }, [open]);

  if (!open) return null;

  // Build the chain: events + decisions sorted by time.
  const items = [];
  (log ? log.events : []).forEach((e) =>
    items.push({ t: e.started_at, kind: "event", ref: e }));
  (log ? log.decisions : []).forEach((d) =>
    items.push({ t: d.timestamp, kind: "decision", ref: d }));
  items.sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0));

  // Find the recorded snapshot at-or-before the selected item's clock.
  const tl = log ? log.timeline : [];
  const item = items[sel];
  let snap = null;
  if (item && tl.length) {
    snap = tl[0].snapshot;
    for (const e of tl) { if (e.clock <= item.t) snap = e.snapshot; else break; }
  }
  const mapState = snap ? { ...snap, routes: staticRoutes,
    events: snap.active_events || [], decisions: snap.pending_decisions || [],
    vehicles: snap.vehicles || [], customers: snap.customers || [] } : null;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal daylog" style={{ width: "92vw", height: "88vh", display: "flex" }}
        onClick={(e) => e.stopPropagation()}>
        <div style={{ width: 360, overflowY: "auto", borderRight: "1px solid var(--border)" }}>
          <div className="panel-head"><h2>Nhật ký ngày</h2>
            <button className="btn ghost icon" style={{ marginLeft: "auto" }} onClick={onClose}><Icon name="x" size={15}/></button>
          </div>
          {items.map((it, i) => {
            const isEv = it.kind === "event";
            const r = it.ref;
            const label = isEv ? (EVENT_TYPES[r.event_type] || {}).label || r.event_type
                               : (ACTIONS[r.action] || {}).label || r.action;
            const col = isEv ? SEVERITY[r.severity].color : "#60a5fa";
            return (
              <div key={i} className={"event-row" + (sel === i ? " sel" : "")}
                style={{ "--ev-accent": col }} onClick={() => setSel(i)}>
                <div className="ev-main">
                  <div className="ev-top">
                    <span className="ev-type">{isEv ? "● Sự kiện" : "→ Quyết định"}: {label}</span>
                  </div>
                  <div className="ev-meta">
                    <span className="ev-target">{isEv ? r.target : (r.event_id || "—")}</span>
                    <span className="ev-age mono">{fmtClock(it.t)}</span>
                  </div>
                </div>
              </div>
            );
          })}
          {items.length === 0 && <div className="empty"><div className="e-sub">Chưa có sự kiện nào trong ngày.</div></div>}
        </div>
        <div style={{ flex: 1, position: "relative" }}>
          {mapState ? <DispatchMap state={mapState} speed={1}/>
                    : <div className="empty" style={{ marginTop: 80 }}><div className="e-sub">Chọn một mốc thời gian để xem bản đồ.</div></div>}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DayLogOverlay });
```

- [ ] **Step 3: Load the script in `index.html`**

In `fleet/ui/web/index.html`, add after the `panels.jsx` line (`:389`):

```html
<script type="text/babel" src="daylog.jsx?v=1"></script>
```

(`daylog.jsx` must load after `map.jsx` and `panels.jsx` since it uses `DispatchMap`, `EVENT_TYPES`, `ACTIONS`, `SEVERITY`, `fmtClock`.)

- [ ] **Step 4: Add the header button + overlay in `app.jsx`**

Add state in `App`: `const [dayLogOpen, setDayLogOpen] = React.useState(false);`

In the header, add a button (e.g. right after `<KPIBar state={state}/>`):

```javascript
        <button className="btn ghost" onClick={() => setDayLogOpen(true)} title="Nhật ký ngày">
          <Icon name="clock" size={15}/> Nhật ký ngày
        </button>
```

Before the closing `</div>` of the app root (next to `<SettingsModal .../>`), add:

```javascript
      <DayLogOverlay open={dayLogOpen} onClose={() => setDayLogOpen(false)}/>
```

Bump `app.jsx`, `api.jsx`, and `index.html`'s relevant `?v=` query suffixes.

- [ ] **Step 5: Manual verification**

Run: `python -m fleet.ui.server`
Open `http://127.0.0.1:8686`. Dispatch some orders, press Play for ~10 ticks, trigger an incident via the Field Report panel, then click **"Nhật ký ngày"**. Verify:
- The left list shows an interleaved event → decision → event chain with timestamps.
- Clicking a node renders a mini-map of that moment (roads visible from static routes, vehicles/events positioned per the recorded snapshot).
- Closing the overlay (X or backdrop) returns to the live control room unchanged.

- [ ] **Step 6: Commit**

```bash
git add fleet/ui/web/daylog.jsx fleet/ui/web/api.jsx fleet/ui/web/index.html fleet/ui/web/app.jsx
git commit -m "feat(ui): full-screen Day-Log replay overlay"
```

---

## Final verification

- [ ] Run the whole backend suite: `python -m pytest tests/ -q` → all PASS.
- [ ] Manual end-to-end: reset world → inbox full → dispatch a wave → progress updates → Play → incident → approve/reject → open Day-Log → review the chain + mini-maps.

---

## Notes for the implementer

- **No new `WorldState` schema fields.** Every lifecycle state is derived from `state.plan` + `customers.orders`. `controller.timeline` is view-model cache, not world data.
- **Gating is the subtle part.** The world no longer plans by itself; only `dispatch_all` / `dispatch_orders` create routes, and gated re-solves are scoped to already-dispatched customers (Tasks 4 & 5) so a reroute never silently dispatches an inbox order.
- **No screenshotting.** The Day-Log mini-map re-renders recorded view-model snapshots through the existing `DispatchMap`; static road geometry is fetched once and merged in to keep timeline entries small.
- **In-browser React.** No build step; components are registered on `window` and scripts are ordered in `index.html`. Bump `?v=` query suffixes after editing a `.jsx` file or the browser will serve a cached copy.
