# M3 (part 2) — CpuSolver via Google OR-Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stub `CpuSolver` with a real VRPTW solver (Google OR-Tools) that honors hard capacity, time windows, per-`veh_type` travel times, and drops un-servable visits via penalty disjunctions — then write the solved routes into `state.plan`.

**Architecture:** `CpuSolver.solve(RoutingProblem) -> RoutingSolution` builds an OR-Tools `RoutingModel`: one transit callback per `veh_type` (travel + service), a `"Time"` dimension with per-node/per-vehicle time windows, a hard `"Capacity"` dimension, and `AddDisjunction` per task (penalty scaled by priority) so infeasible orders drop into `dropped` (→ DEFER). Default search is deterministic (`PATH_CHEAPEST_ARC`, no time limit); a setting enables `GUIDED_LOCAL_SEARCH` for demo quality. A new `plan_routes(state, optimizer)` orchestrates `build_routing_problem → solve → state.plan`.

**Tech Stack:** Python 3.10+, **Google OR-Tools** (`ortools`), dataclasses, pytest. Same repo/venv/branch.

---

## Context

- Continues branch **`feat/base-project`** (plans 1–4 executed & green; 77 passing).
- Builds on Plan 4: consumes `build_routing_problem` and the per-`veh_type` `time_matrix`.
- **Adds the `ortools` dependency** (CPU-only — no GPU, no API key). cuOpt (M4) will plug in behind the same `RouteOptimizer` interface.
- API grounded in the official OR-Tools docs: [VRPTW](https://developers.google.com/optimization/routing/vrptw) and [Penalties / dropping visits](https://developers.google.com/optimization/routing/penalties).
- Changes: `requirements.txt`, `config/settings.py`, `fleet/routing/cpu_solver.py` (rewrite), `fleet/factory.py` (pass settings), `tests/test_config.py` (+assert), `tests/test_cpu_solver.py` (rewrite — stub assertions no longer hold), new `fleet/routing/planner.py` + `tests/test_planner.py`.

**Solver modeling decisions (documented in code):**
- All times → integer **minutes from `base`** (the earliest of all shift starts / task starts); converted back to datetimes on output.
- Transit = `travel_time[from][to] + service_time[from]`; unreachable (`INF`) → `10_000_000` (effectively forbidden).
- Capacity is **hard** (spec §6.9): `AddDimensionWithVehicleCapacity`.
- Vehicle start **and** end constrained to the shift window (return to depot within shift, spec §6.9).
- Drop penalty `= 100_000 * (5 - priority)` (≫ any route time, so feasible visits are always kept; when forced to drop, lower-priority drops first).
- Determinism: default `PATH_CHEAPEST_ARC`, no metaheuristic/time-limit. `settings.solver_time_limit_sec > 0` enables `GUIDED_LOCAL_SEARCH` + that limit.

Environment reminder (Windows / PowerShell): activate venv `.\.venv\Scripts\Activate.ps1`; run tests `pytest -v`; commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Only `git add` the files named in each task.

---

### Task 1: Add `ortools` dependency + solver setting

**Files:**
- Modify: `requirements.txt`
- Modify: `config/settings.py` (`Settings` + `load_settings`)
- Test: `tests/test_config.py` (extend `test_defaults`, add env test)

- [ ] **Step 1: Write the failing test**

In `tests/test_config.py`, add to the end of `test_defaults`:
```python
    assert s.solver_time_limit_sec == 0
```
And append:
```python
def test_solver_time_limit_env_override():
    s = load_settings(env={"SOLVER_TIME_LIMIT_SEC": "5"})
    assert s.solver_time_limit_sec == 5
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'solver_time_limit_sec'`.

- [ ] **Step 3: Add the setting**

In `config/settings.py`, replace:
```python
    demand_noise: float = 0.3                        # M2: demand multiplicative noise (±)
    restock_interval_min: int = 240                  # M2: depot restock cadence (sim minutes)
```
with:
```python
    demand_noise: float = 0.3                        # M2: demand multiplicative noise (±)
    restock_interval_min: int = 240                  # M2: depot restock cadence (sim minutes)
    solver_time_limit_sec: int = 0                   # M3: >0 enables OR-Tools GLS (else deterministic)
```
And in `load_settings`, replace:
```python
        demand_noise=float(e.get("DEMAND_NOISE", "0.3")),
        restock_interval_min=int(e.get("RESTOCK_INTERVAL_MIN", "240")),
    )
```
with:
```python
        demand_noise=float(e.get("DEMAND_NOISE", "0.3")),
        restock_interval_min=int(e.get("RESTOCK_INTERVAL_MIN", "240")),
        solver_time_limit_sec=int(e.get("SOLVER_TIME_LIMIT_SEC", "0")),
    )
```

- [ ] **Step 4: Add `ortools` to `requirements.txt`**

Replace the contents of `requirements.txt` with:
```text
pytest>=7.4
ortools>=9.8
```

- [ ] **Step 5: Install and verify**

Run (PowerShell, venv active):
```powershell
pip install -r requirements.txt
pytest tests/test_config.py -v
```
Expected: ortools installs; config tests PASS. Sanity-check the import:
```powershell
python -c "from ortools.constraint_solver import pywrapcp, routing_enums_pb2; print('ortools ok')"
```
Expected: `ortools ok`.

- [ ] **Step 6: Commit**

```powershell
git add requirements.txt config/settings.py tests/test_config.py
git commit -m "feat(routing): add ortools dependency + solver_time_limit_sec setting" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Real `CpuSolver` (OR-Tools VRPTW)

**Files:**
- Modify: `fleet/routing/cpu_solver.py` (full rewrite)
- Modify: `fleet/factory.py` (construct `CpuSolver(settings)`)
- Test: `tests/test_cpu_solver.py` (full rewrite — the stub assertions are obsolete)

- [ ] **Step 1: Rewrite the tests (property-based)**

Replace the entire contents of `tests/test_cpu_solver.py` with:
```python
from datetime import datetime, timedelta

from fleet.contracts.interfaces import RouteOptimizer
from fleet.contracts.dto import (
    RoutingProblem, FleetVehicleSpec, TaskSpec, RoutingSolution,
)
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.matrix import build_routing_problem
from fleet.scenarios import build_sample_state


def test_conforms_to_protocol():
    assert isinstance(CpuSolver(), RouteOptimizer)


def test_serves_all_feasible_sample_customers():
    problem = build_routing_problem(build_sample_state())
    sol = CpuSolver().solve(problem)
    assert isinstance(sol, RoutingSolution)
    assert sol.feasible is True
    served = {st.customer_id for stops in sol.routes.values() for st in stops}
    assert served == {"C001", "C002", "C003", "C004"}
    assert sol.dropped == []


def test_each_customer_served_at_most_once():
    problem = build_routing_problem(build_sample_state())
    sol = CpuSolver().solve(problem)
    served = [st.customer_id for stops in sol.routes.values() for st in stops]
    assert len(served) == len(set(served))


def test_respects_capacity():
    problem = build_routing_problem(build_sample_state())
    sol = CpuSolver().solve(problem)
    cap = {f.id: f.capacity_kg for f in problem.fleet}
    demand = {t.customer_id: t.demand_kg for t in problem.tasks}
    for vid, stops in sol.routes.items():
        assert sum(demand[st.customer_id] for st in stops) <= cap[vid]


def test_respects_time_windows():
    problem = build_routing_problem(build_sample_state())
    sol = CpuSolver().solve(problem)
    tw = {t.customer_id: (t.tw_start, t.tw_end) for t in problem.tasks}
    for stops in sol.routes.values():
        for st in stops:
            start, end = tw[st.customer_id]
            assert start <= st.arrival <= end


def test_drops_infeasible_customer():
    t0 = datetime(2026, 6, 5, 6, 0)
    # shift 6:00-7:00; C1 window 6:00-6:05 but 10 min away -> cannot be served
    problem = RoutingProblem(
        locations=["DEPOT", "C1"], depot_id="DEPOT",
        time_matrix={"truck": [[0.0, 10.0], [10.0, 0.0]]},
        fleet=[FleetVehicleSpec("V1", 500, "truck", t0, t0 + timedelta(hours=1))],
        tasks=[TaskSpec("C1", 20.0, t0, t0 + timedelta(minutes=5), 10.0, 1)],
    )
    sol = CpuSolver().solve(problem)
    assert sol.dropped == ["C1"]
    assert sol.routes["V1"] == []


def test_deterministic():
    problem = build_routing_problem(build_sample_state())
    a = CpuSolver().solve(problem)
    b = CpuSolver().solve(problem)
    norm = lambda s: {v: [(st.customer_id, st.arrival) for st in stops]
                      for v, stops in s.routes.items()}
    assert norm(a) == norm(b)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_cpu_solver.py -v`
Expected: FAIL — the stub drops every customer, so `test_serves_all_feasible_sample_customers` fails (`set() == {...}`).

- [ ] **Step 3: Rewrite `fleet/routing/cpu_solver.py`**

Replace the entire contents of `fleet/routing/cpu_solver.py` with:
```python
"""CPU route optimizer using Google OR-Tools (VRPTW).

Honors hard capacity, time windows, per-veh_type travel times, and drops
un-servable visits via penalty disjunctions. Deterministic by default
(PATH_CHEAPEST_ARC, no time limit); set settings.solver_time_limit_sec > 0 to
enable GUIDED_LOCAL_SEARCH. Replaces the M1 stub."""

from datetime import datetime, timedelta
from typing import Dict, List

from ortools.constraint_solver import routing_enums_pb2, pywrapcp

from fleet.contracts.dto import RoutingProblem, RoutingSolution, SolvedStop

_UNREACHABLE = 10_000_000        # minutes; effectively forbids an arc
_DROP_PENALTY_BASE = 100_000     # >> any route time, so feasible visits are kept


class CpuSolver:
    def __init__(self, settings=None):
        self.settings = settings

    def solve(self, problem: RoutingProblem) -> RoutingSolution:
        n = len(problem.locations)
        num_vehicles = len(problem.fleet)

        if not problem.tasks or num_vehicles == 0:
            return RoutingSolution(
                routes={f.id: [] for f in problem.fleet},
                dropped=[t.customer_id for t in problem.tasks],
                feasible=True, metrics={"total_time_min": 0.0})

        depot = problem.locations.index(problem.depot_id)

        # ---- everything in integer minutes from the earliest moment ----
        base = min([f.shift_start for f in problem.fleet]
                   + [t.tw_start for t in problem.tasks])

        def mins(dt: datetime) -> int:
            return int(round((dt - base).total_seconds() / 60.0))

        task_by_loc = {t.customer_id: t for t in problem.tasks}
        demand = [0] * n
        service = [0] * n
        windows: List = [None] * n
        for i, loc in enumerate(problem.locations):
            t = task_by_loc.get(loc)
            if t is not None:
                demand[i] = int(round(t.demand_kg))
                service[i] = int(round(t.service_time_min))
                windows[i] = (mins(t.tw_start), mins(t.tw_end))

        horizon = max([mins(f.shift_end) for f in problem.fleet]
                      + [mins(t.tw_end) for t in problem.tasks]) + 1

        manager = pywrapcp.RoutingIndexManager(n, num_vehicles, depot)
        routing = pywrapcp.RoutingModel(manager)

        def time_int(value: float) -> int:
            return _UNREACHABLE if value == float("inf") else int(round(value))

        # one transit callback per veh_type: travel + service at the 'from' node
        type_cb: Dict[str, int] = {}
        for vt, matrix in problem.time_matrix.items():
            def make_cb(mat):
                def cb(from_index, to_index):
                    i = manager.IndexToNode(from_index)
                    j = manager.IndexToNode(to_index)
                    return time_int(mat[i][j]) + service[i]
                return cb
            type_cb[vt] = routing.RegisterTransitCallback(make_cb(matrix))

        transit_indices = []
        for vehicle_id, f in enumerate(problem.fleet):
            cb_index = type_cb[f.veh_type]
            routing.SetArcCostEvaluatorOfVehicle(cb_index, vehicle_id)
            transit_indices.append(cb_index)

        routing.AddDimensionWithVehicleTransits(
            transit_indices, horizon, horizon, False, "Time")
        time_dim = routing.GetDimensionOrDie("Time")

        for i in range(n):
            if windows[i] is not None:
                time_dim.CumulVar(manager.NodeToIndex(i)).SetRange(*windows[i])
        for vehicle_id, f in enumerate(problem.fleet):
            s, e = mins(f.shift_start), mins(f.shift_end)
            time_dim.CumulVar(routing.Start(vehicle_id)).SetRange(s, e)
            time_dim.CumulVar(routing.End(vehicle_id)).SetRange(s, e)
            routing.AddVariableMinimizedByFinalizer(
                time_dim.CumulVar(routing.Start(vehicle_id)))
            routing.AddVariableMinimizedByFinalizer(
                time_dim.CumulVar(routing.End(vehicle_id)))

        # capacity (hard, spec §6.9)
        def demand_cb(from_index):
            return demand[manager.IndexToNode(from_index)]
        demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
        routing.AddDimensionWithVehicleCapacity(
            demand_idx, 0, [int(round(f.capacity_kg)) for f in problem.fleet],
            True, "Capacity")

        # droppable visits: penalty scaled by priority (1=urgent kept hardest)
        for i in range(n):
            t = task_by_loc.get(problem.locations[i])
            if t is not None:
                penalty = _DROP_PENALTY_BASE * (5 - max(1, min(4, t.priority)))
                routing.AddDisjunction([manager.NodeToIndex(i)], penalty)

        params = pywrapcp.DefaultRoutingSearchParameters()
        params.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
        limit = int(getattr(self.settings, "solver_time_limit_sec", 0) or 0)
        if limit > 0:
            params.local_search_metaheuristic = (
                routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH)
            params.time_limit.FromSeconds(limit)

        solution = routing.SolveWithParameters(params)
        if solution is None:
            return RoutingSolution(
                routes={f.id: [] for f in problem.fleet},
                dropped=[t.customer_id for t in problem.tasks],
                feasible=False, metrics={"total_time_min": 0.0})

        return self._read(problem, manager, routing, solution, time_dim,
                          demand, service, base, depot)

    @staticmethod
    def _read(problem, manager, routing, solution, time_dim,
              demand, service, base, depot) -> RoutingSolution:
        routes: Dict[str, List[SolvedStop]] = {}
        total_time = 0
        for vehicle_id, f in enumerate(problem.fleet):
            node_indices = []
            index = routing.Start(vehicle_id)
            while not routing.IsEnd(index):
                node_indices.append(index)
                index = solution.Value(routing.NextVar(index))
            remaining = sum(demand[manager.IndexToNode(ix)] for ix in node_indices)
            stops: List[SolvedStop] = []
            for ix in node_indices:
                node = manager.IndexToNode(ix)
                if node == depot:
                    continue
                arrival = base + timedelta(
                    minutes=solution.Value(time_dim.CumulVar(ix)))
                departure = arrival + timedelta(minutes=service[node])
                remaining -= demand[node]
                stops.append(SolvedStop(
                    customer_id=problem.locations[node], arrival=arrival,
                    departure=departure, load_after=float(remaining)))
            routes[f.id] = stops
            if stops:
                total_time += (
                    solution.Value(time_dim.CumulVar(routing.End(vehicle_id)))
                    - solution.Value(time_dim.CumulVar(routing.Start(vehicle_id))))

        dropped = []
        for i in range(len(problem.locations)):
            if i == depot:
                continue
            index = manager.NodeToIndex(i)
            if solution.Value(routing.NextVar(index)) == index:
                dropped.append(problem.locations[i])

        served = {st.customer_id for stops in routes.values() for st in stops}
        metrics = {"total_time_min": float(total_time),
                   "served": float(len(served)), "dropped": float(len(dropped))}
        return RoutingSolution(routes=routes, dropped=dropped,
                               feasible=True, metrics=metrics)
```

- [ ] **Step 4: Pass settings into `CpuSolver` from the factory**

In `fleet/factory.py`, replace:
```python
    if settings.routing_engine == "cuopt":
        optimizer: RouteOptimizer = CpuSolver()  # TODO M4: CuOptAdapter(settings)
    else:
        optimizer = CpuSolver()
```
with:
```python
    if settings.routing_engine == "cuopt":
        optimizer: RouteOptimizer = CpuSolver(settings)  # TODO M4: CuOptAdapter(settings)
    else:
        optimizer = CpuSolver(settings)
```

- [ ] **Step 5: Run to verify pass + full suite green**

Run: `pytest -q`
Expected: PASS (cpu_solver property tests + factory + everything else).

- [ ] **Step 6: Commit**

```powershell
git add fleet/routing/cpu_solver.py fleet/factory.py tests/test_cpu_solver.py
git commit -m "feat(routing): real CpuSolver (OR-Tools VRPTW: capacity, time windows, drops)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `plan_routes` — write solved routes into `state.plan`

**Files:**
- Create: `fleet/routing/planner.py`
- Test: `tests/test_planner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planner.py`:
```python
from fleet.routing.planner import plan_routes
from fleet.routing.cpu_solver import CpuSolver
from fleet.contracts.state import VehicleRoute, Stop
from fleet.scenarios import build_sample_state


def test_plan_routes_populates_state_plan():
    s = build_sample_state()
    dropped = plan_routes(s, CpuSolver())
    assert dropped == []
    assert s.plan  # non-empty
    served = {st.customer_id for r in s.plan.values() for st in r.stops}
    assert served == {"C001", "C002", "C003", "C004"}
    for r in s.plan.values():
        assert isinstance(r, VehicleRoute)
        assert all(isinstance(st, Stop) for st in r.stops)
        assert [st.sequence for st in r.stops] == list(range(1, len(r.stops) + 1))


def test_plan_routes_stops_have_consistent_times():
    s = build_sample_state()
    plan_routes(s, CpuSolver())
    for r in s.plan.values():
        for st in r.stops:
            assert st.planned_departure >= st.planned_arrival
        assert r.start_time == r.stops[0].planned_arrival
        assert r.end_time == r.stops[-1].planned_departure


def test_plan_routes_only_routes_with_stops():
    s = build_sample_state()
    plan_routes(s, CpuSolver())
    # every stored route has at least one stop (empty routes are omitted)
    assert all(len(r.stops) >= 1 for r in s.plan.values())
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.routing.planner'`.

- [ ] **Step 3: Create `fleet/routing/planner.py`**

```python
"""Orchestrates planning: build the problem, solve it, and write the resulting
routes into state.plan. Returns the dropped customer ids (candidates for DEFER).

Keeps the loop/agent decoupled from the optimizer impl: they call plan_routes
with whichever RouteOptimizer the factory selected."""

from typing import List

from fleet.contracts.state import WorldState, VehicleRoute, Stop
from fleet.contracts.interfaces import RouteOptimizer
from fleet.routing.matrix import build_routing_problem


def plan_routes(state: WorldState, optimizer: RouteOptimizer,
                depot_id: str = "DEPOT") -> List[str]:
    problem = build_routing_problem(state, depot_id)
    solution = optimizer.solve(problem)
    state.plan = {}
    for vid, solved in solution.routes.items():
        if not solved:
            continue
        stops = [
            Stop(customer_id=ss.customer_id, sequence=k,
                 planned_arrival=ss.arrival, planned_departure=ss.departure,
                 load_after_stop=ss.load_after)
            for k, ss in enumerate(solved, start=1)
        ]
        state.plan[vid] = VehicleRoute(
            vehicle_id=vid, stops=stops,
            total_time=solution.metrics.get("total_time_min", 0.0),
            start_time=stops[0].planned_arrival,
            end_time=stops[-1].planned_departure,
        )
    return solution.dropped
```

- [ ] **Step 4: Run to verify pass + full suite green**

Run: `pytest -q`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```powershell
git add fleet/routing/planner.py tests/test_planner.py
git commit -m "feat(routing): plan_routes writes solved VehicleRoutes into state.plan" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Definition of done

- `pytest -q` green; `test_cpu_solver.py` proves: all feasible sample customers served, none double-served, capacity respected, arrivals within time windows, an impossible-window customer is dropped, and solving is deterministic. `test_planner.py` proves `state.plan` is populated with well-formed `VehicleRoute`/`Stop` objects.
- `CpuSolver` honors hard capacity + time windows + per-`veh_type` matrices; un-servable orders land in `dropped`.
- Default solve is deterministic and instant; `SOLVER_TIME_LIMIT_SEC>0` opts into GLS.
- `ortools` is the only new dependency; runs on CPU (no GPU, no API key).

**Next plan: M3 part 3 — vehicle movement + reroute.** Wire `plan_routes` into `loop.py` (plan at start / when plan empty); advance vehicles along their `VehicleRoute` each tick (consume `effective_time` between stops, update `Vehicle.pos`/`status`/`current_stop_index`, set `Stop.actual_arrival`); on edge-status events (TRAFFIC/FLOODED/BLOCKED) recompute the affected matrix entries and re-solve (reroute = matrix update + `plan_routes`), feeding `dropped` into DEFER decisions. Then M4 (`CuOptAdapter` behind the same interface), M5 (ClaudeAgent), M6 (Ewma+ZScore), M7 (Streamlit UI).
