# M4 — CuOptAdapter (NVIDIA cuOpt behind RouteOptimizer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second `RouteOptimizer` implementation — `CuOptAdapter` — that solves the same `RoutingProblem` by calling an NVIDIA cuOpt server, so the engine is swappable from CPU (OR-Tools) to GPU (cuOpt) by config alone, with a safe fallback to `CpuSolver` when no cuOpt endpoint is configured.

**Architecture:** The adapter is two **pure, fully-testable translation functions** (`to_cuopt_request`: `RoutingProblem` → cuOpt JSON; `from_cuopt_response`: cuOpt JSON → `RoutingSolution`) plus a thin `CuOptAdapter.solve` that wires them around an **injected transport** callable (`request_dict -> response_dict`). Tests drive the translators and `solve` with canned cuOpt JSON, so **no GPU and no live server are needed**. The real transport (cuOpt self-hosted thin client / HTTP `POST /cuopt/request`) is created lazily and only used at runtime when an endpoint is set.

**Tech Stack:** Python 3.10+, dataclasses, pytest. Optional runtime-only dependency: `cuopt-sh-client` (NVIDIA cuOpt self-hosted thin client) — imported lazily, **not** required for tests. Same repo/venv/branch.

---

## Context

- Continues branch **`feat/base-project`** (plans 1–6: M0–M3 complete & green; ~95+ passing after M3 part 3).
- Implements the M4 milestone from the plan series: "CuOptAdapter behind the `RouteOptimizer` interface (GPU solver plugs in beside `CpuSolver`, selected by `config/settings.py`)."
- The `RouteOptimizer` Protocol (`fleet/contracts/interfaces.py`) is a single method `solve(problem: RoutingProblem) -> RoutingSolution`. `CpuSolver` already implements it; `CuOptAdapter` must produce the **same** `RoutingSolution` shape so the loop/planner are unchanged.
- `config/settings.py` already has `routing_engine: str = "cpu"  # cpu | cuopt` and `cuopt_endpoint: str = ""`. The factory currently falls `cuopt` back to `CpuSolver` (TODO M4). This plan removes that TODO.

**cuOpt API grounding** (NVIDIA cuOpt self-hosted, `POST /cuopt/request`; verified against the official docs):
- Request top-level keys: `cost_matrix_data`, `travel_time_matrix_data`, `task_data`, `fleet_data`.
  - `cost_matrix_data.data` / `travel_time_matrix_data.data` = `{ "<vehicle_type_int>": NxN_int_matrix }` (one matrix per vehicle *type*, keyed by an integer-as-string).
  - `task_data`: `task_locations` (matrix indices), `demand` (shape `[n_dims][n_tasks]`), `task_time_windows` (`[[start,end],...]`), `service_times` (`[s,...]`), `penalties` (`[p,...]` — penalty for leaving a task unserved; lets the solver drop infeasible tasks).
  - `fleet_data`: `vehicle_locations` (`[[start_idx,end_idx],...]`), `capacities` (shape `[n_dims][n_vehicles]`), `vehicle_time_windows` (`[[start,end],...]`), `vehicle_types` (`[int,...]`, one per vehicle, referencing the matrix keys).
- Response: `response.solver_response` with `status` (0 = success), `vehicle_data` = `{ "<vehicle_idx>": { "task_id": [...], "route": [...], "arrival_stamp": [...] } }`, and `dropped_tasks` = `{ "task_id": [...], "task_index": [...] }`. In `task_id`, the depot appears as the literal `"Depot"`; served tasks appear as their **task index** rendered as a string (e.g. `"0"`, `"1"`). `route` includes the return-to-depot leg, so `len(route) == len(task_id) + 1`; `arrival_stamp` aligns with `task_id`.
- Submission: the self-hosted thin client `CuOptServiceSelfHostClient.get_optimized_routes(data)` handles the POST + polling (default `localhost:5000`); managed/NVIDIA-hosted adds an auth header. We keep all of that behind the injected transport so it never runs in tests.

Docs: [Self-Hosted Client API](https://docs.nvidia.com/cuopt/user-guide/latest/cuopt-server/client-api/sh-cli-api.html), [Routing examples](https://archive.docs.nvidia.com/cuopt/user-guide/26.02.00/cuopt-server/examples/routing-examples.html).

**Modeling decisions (documented in code):**
- All times → integer **minutes from `base`** (earliest of all `shift_start` / `tw_start`) — identical convention to `CpuSolver`, so a shared `_base_time(problem)` is the single source of truth and the matrices/time-windows/arrival stamps share one origin.
- One capacity dimension (kg). `demand = [[...]]`, `capacities = [[...]]` (outer length 1).
- Unreachable matrix cell (`inf`) → `10_000_000` (effectively forbidden) — same constant/intent as `CpuSolver`.
- Drop penalty `= 100_000 * (5 - clamp(priority,1,4))` — same scaling as `CpuSolver` so urgent (priority 1) tasks resist dropping hardest.
- Vehicle types: stable mapping `sorted(time_matrix.keys())` → `0,1,2,...`, used for both matrix keys and per-vehicle `vehicle_types`.
- `load_after` is reconstructed the same way as `CpuSolver._read` (sum demands on the route, subtract as you go), since cuOpt does not return per-stop remaining load.

**Changes:** new `fleet/routing/cuopt_adapter.py`, new `tests/test_cuopt_adapter.py`, modify `fleet/factory.py` (select `CuOptAdapter`), modify `tests/test_factory.py` (selection assertions — create if absent), modify `requirements.txt` (document the optional dep as a comment).

Environment reminder (Windows / PowerShell): activate venv `.\.venv\Scripts\Activate.ps1`; run tests `pytest -v`; commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Only `git add` the files named in each task — do NOT touch `Guide.md`, `problem.txt`, `docs/PROBLEM_STATEMENT.md`.

---

### Task 1: Pure request translation `to_cuopt_request`

**Files:**
- Create: `fleet/routing/cuopt_adapter.py`
- Test: new `tests/test_cuopt_adapter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cuopt_adapter.py`:
```python
from datetime import datetime

from fleet.contracts.dto import (
    RoutingProblem, FleetVehicleSpec, TaskSpec,
)
from fleet.routing.cuopt_adapter import (
    to_cuopt_request, _base_time, _vehicle_type_keys,
)


def _problem():
    t0 = datetime(2026, 6, 4, 6, 0)
    t_end = datetime(2026, 6, 4, 18, 0)
    # locations: depot + two customers; one veh_type "truck"
    matrix = [
        [0.0, 10.0, 20.0],
        [10.0, 0.0, 15.0],
        [20.0, 15.0, 0.0],
    ]
    fleet = [
        FleetVehicleSpec("V001", 500, "truck", t0, t_end),
        FleetVehicleSpec("V002", 300, "truck", t0, t_end),
    ]
    tasks = [
        TaskSpec("C001", 40, datetime(2026, 6, 4, 7, 0),
                 datetime(2026, 6, 4, 9, 0), 10, priority=1),
        TaskSpec("C002", 60, datetime(2026, 6, 4, 8, 0),
                 datetime(2026, 6, 4, 12, 0), 10, priority=3),
    ]
    return RoutingProblem(
        locations=["DEPOT", "C001", "C002"], depot_id="DEPOT",
        time_matrix={"truck": matrix}, fleet=fleet, tasks=tasks)


def test_base_time_is_earliest_moment():
    p = _problem()
    # earliest of shift starts (06:00) and task tw_starts (07:00, 08:00)
    assert _base_time(p) == datetime(2026, 6, 4, 6, 0)


def test_vehicle_type_keys_are_stable_integers():
    p = _problem()
    assert _vehicle_type_keys(p) == {"truck": 0}


def test_request_has_cuopt_shape():
    p = _problem()
    req = to_cuopt_request(p)

    # matrices keyed by integer-as-string vehicle type, int-valued
    assert req["cost_matrix_data"]["data"]["0"] == [
        [0, 10, 20], [10, 0, 15], [20, 15, 0]]
    assert req["travel_time_matrix_data"]["data"]["0"][1][2] == 15

    td = req["task_data"]
    assert td["task_locations"] == [1, 2]              # indices into locations
    assert td["demand"] == [[40, 60]]                  # [n_dims][n_tasks]
    assert td["service_times"] == [10, 10]
    # tw in minutes from base (06:00): C001 07:00-09:00 -> 60..180
    assert td["task_time_windows"] == [[60, 180], [120, 360]]
    # penalty = 100000 * (5 - priority): priority 1 -> 400000, 3 -> 200000
    assert td["penalties"] == [400000, 200000]

    fd = req["fleet_data"]
    assert fd["vehicle_locations"] == [[0, 0], [0, 0]]  # start=end=depot index
    assert fd["capacities"] == [[500, 300]]             # [n_dims][n_vehicles]
    assert fd["vehicle_types"] == [0, 0]
    assert fd["vehicle_time_windows"] == [[0, 720], [0, 720]]  # 06:00..18:00


def test_unreachable_cell_becomes_forbidden_constant():
    p = _problem()
    p.time_matrix["truck"][0][2] = float("inf")
    req = to_cuopt_request(p)
    assert req["cost_matrix_data"]["data"]["0"][0][2] == 10_000_000
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_cuopt_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.routing.cuopt_adapter'`.

- [ ] **Step 3: Implement the translator**

Create `fleet/routing/cuopt_adapter.py`:
```python
"""GPU route optimizer adapter for NVIDIA cuOpt (self-hosted).

Same RouteOptimizer interface and RoutingSolution shape as CpuSolver, so the
loop/planner don't change. The two translation functions are pure and fully
unit-tested with canned JSON; the network transport is injected (and created
lazily) so no GPU/server is needed to run the suite. Time convention matches
CpuSolver: integer minutes from `_base_time(problem)`.

cuOpt request/response schema: NVIDIA cuOpt self-hosted `POST /cuopt/request`.
"""

from datetime import datetime, timedelta
from typing import Callable, Dict, List

from fleet.contracts.dto import RoutingProblem, RoutingSolution, SolvedStop

_UNREACHABLE = 10_000_000        # minutes; effectively forbids an arc (matches CpuSolver)
_DROP_PENALTY_BASE = 100_000     # penalty for leaving a task unserved
_STATUS_OK = 0


def _base_time(problem: RoutingProblem) -> datetime:
    """Earliest shift/task start — the origin for all integer-minute values."""
    return min([f.shift_start for f in problem.fleet]
               + [t.tw_start for t in problem.tasks])


def _vehicle_type_keys(problem: RoutingProblem) -> Dict[str, int]:
    """Stable veh_type -> integer matrix key."""
    return {vt: i for i, vt in enumerate(sorted(problem.time_matrix))}


def _int_matrix(matrix: List[List[float]]) -> List[List[int]]:
    return [[_UNREACHABLE if v == float("inf") else int(round(v)) for v in row]
            for row in matrix]


def to_cuopt_request(problem: RoutingProblem) -> dict:
    base = _base_time(problem)

    def mins(dt: datetime) -> int:
        return int(round((dt - base).total_seconds() / 60.0))

    depot = problem.locations.index(problem.depot_id)
    type_keys = _vehicle_type_keys(problem)

    matrices = {str(type_keys[vt]): _int_matrix(mat)
                for vt, mat in problem.time_matrix.items()}

    task_locations, demand_row, tws, service, penalties = [], [], [], [], []
    for t in problem.tasks:
        task_locations.append(problem.locations.index(t.customer_id))
        demand_row.append(int(round(t.demand_kg)))
        tws.append([mins(t.tw_start), mins(t.tw_end)])
        service.append(int(round(t.service_time_min)))
        penalties.append(_DROP_PENALTY_BASE * (5 - max(1, min(4, t.priority))))

    veh_locations, cap_row, vtws, veh_types = [], [], [], []
    for f in problem.fleet:
        veh_locations.append([depot, depot])
        cap_row.append(int(round(f.capacity_kg)))
        vtws.append([mins(f.shift_start), mins(f.shift_end)])
        veh_types.append(type_keys[f.veh_type])

    return {
        "cost_matrix_data": {"data": matrices},
        "travel_time_matrix_data": {"data": matrices},
        "task_data": {
            "task_locations": task_locations,
            "demand": [demand_row],
            "task_time_windows": tws,
            "service_times": service,
            "penalties": penalties,
        },
        "fleet_data": {
            "vehicle_locations": veh_locations,
            "capacities": [cap_row],
            "vehicle_time_windows": vtws,
            "vehicle_types": veh_types,
        },
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_cuopt_adapter.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```
git add fleet/routing/cuopt_adapter.py tests/test_cuopt_adapter.py
git commit -m "feat(routing): cuOpt request translation (pure, tested)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Pure response translation `from_cuopt_response`

**Files:**
- Modify: `fleet/routing/cuopt_adapter.py`
- Test: `tests/test_cuopt_adapter.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cuopt_adapter.py`:
```python
from datetime import timedelta
from fleet.routing.cuopt_adapter import from_cuopt_response, _base_time


def _canned_response():
    # V001 (vehicle idx 0) serves task 0 (C001) then task 1 (C002); none dropped.
    # arrival_stamp in minutes from base; "Depot" entries bracket the route.
    return {
        "response": {
            "solver_response": {
                "status": 0,
                "num_vehicles": 1,
                "solution_cost": 35.0,
                "vehicle_data": {
                    "0": {
                        "task_id": ["Depot", "0", "1", "Depot"],
                        "route": [0, 1, 2, 0],
                        "arrival_stamp": [0.0, 70.0, 130.0, 150.0],
                    }
                },
                "dropped_tasks": {"task_id": [], "task_index": []},
            }
        },
        "reqId": "test-req",
    }


def test_response_maps_to_routing_solution():
    p = _problem()
    base = _base_time(p)
    sol = from_cuopt_response(p, _canned_response(), base)

    assert sol.feasible is True
    assert sol.dropped == []
    stops = sol.routes["V001"]
    assert [s.customer_id for s in stops] == ["C001", "C002"]
    # arrival = base + arrival_stamp minutes
    assert stops[0].arrival == base + timedelta(minutes=70)
    # departure = arrival + service_time (10 min)
    assert stops[0].departure == base + timedelta(minutes=80)
    # V002 had no vehicle_data -> empty route
    assert sol.routes["V002"] == []
    # load_after: total demand 100 -> after C001 (40) leaves 60, after C002 leaves 0
    assert stops[0].load_after == 60.0
    assert stops[1].load_after == 0.0


def test_dropped_tasks_become_dropped_customer_ids():
    p = _problem()
    base = _base_time(p)
    resp = _canned_response()
    sr = resp["response"]["solver_response"]
    sr["vehicle_data"]["0"] = {
        "task_id": ["Depot", "0", "Depot"],
        "route": [0, 1, 0],
        "arrival_stamp": [0.0, 70.0, 90.0],
    }
    sr["dropped_tasks"] = {"task_id": ["1"], "task_index": [1]}
    sol = from_cuopt_response(p, resp, base)
    assert sol.dropped == ["C002"]
    assert [s.customer_id for s in sol.routes["V001"]] == ["C001"]


def test_nonzero_status_is_infeasible():
    p = _problem()
    base = _base_time(p)
    resp = _canned_response()
    resp["response"]["solver_response"]["status"] = 1
    sol = from_cuopt_response(p, resp, base)
    assert sol.feasible is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_cuopt_adapter.py -v`
Expected: FAIL — `ImportError: cannot import name 'from_cuopt_response'`.

- [ ] **Step 3: Implement the response translator**

Append to `fleet/routing/cuopt_adapter.py`:
```python
def from_cuopt_response(problem: RoutingProblem, response: dict,
                        base: datetime) -> RoutingSolution:
    sr = response["response"]["solver_response"]
    status = sr.get("status", 0)

    routes: Dict[str, List[SolvedStop]] = {f.id: [] for f in problem.fleet}
    total_time = 0.0
    for v_key, vd in sr.get("vehicle_data", {}).items():
        vehicle = problem.fleet[int(v_key)]
        task_ids = vd.get("task_id", [])
        stamps = vd.get("arrival_stamp", [])
        served = [(tid, st) for tid, st in zip(task_ids, stamps)
                  if tid != "Depot"]
        remaining = sum(int(round(problem.tasks[int(tid)].demand_kg))
                        for tid, _ in served)
        stops: List[SolvedStop] = []
        for tid, stamp in served:
            task = problem.tasks[int(tid)]
            arrival = base + timedelta(minutes=float(stamp))
            departure = arrival + timedelta(minutes=task.service_time_min)
            remaining -= int(round(task.demand_kg))
            stops.append(SolvedStop(
                customer_id=task.customer_id, arrival=arrival,
                departure=departure, load_after=float(remaining)))
        routes[vehicle.id] = stops
        if stamps:
            total_time += float(stamps[-1]) - float(stamps[0])

    dropped_idx = sr.get("dropped_tasks", {}).get("task_index", [])
    dropped = [problem.tasks[i].customer_id for i in dropped_idx]

    served_count = sum(len(s) for s in routes.values())
    metrics = {"total_time_min": float(total_time),
               "served": float(served_count), "dropped": float(len(dropped)),
               "solution_cost": float(sr.get("solution_cost", 0.0))}
    return RoutingSolution(routes=routes, dropped=dropped,
                           feasible=(status == _STATUS_OK), metrics=metrics)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_cuopt_adapter.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```
git add fleet/routing/cuopt_adapter.py tests/test_cuopt_adapter.py
git commit -m "feat(routing): cuOpt response -> RoutingSolution translation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `CuOptAdapter.solve` with injected transport

**Files:**
- Modify: `fleet/routing/cuopt_adapter.py`
- Test: `tests/test_cuopt_adapter.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cuopt_adapter.py`:
```python
from fleet.routing.cuopt_adapter import CuOptAdapter
from fleet.contracts.dto import RoutingProblem


def test_solve_uses_transport_and_returns_solution():
    p = _problem()
    captured = {}

    def fake_transport(request: dict) -> dict:
        captured["request"] = request
        return _canned_response()

    adapter = CuOptAdapter(settings=None, transport=fake_transport)
    sol = adapter.solve(p)

    # the transport received a well-formed cuOpt request
    assert captured["request"]["task_data"]["task_locations"] == [1, 2]
    # and the response was translated
    assert [s.customer_id for s in sol.routes["V001"]] == ["C001", "C002"]
    assert sol.feasible is True


def test_solve_short_circuits_empty_problem_without_calling_transport():
    p = RoutingProblem(locations=["DEPOT"], depot_id="DEPOT",
                       time_matrix={"truck": [[0.0]]}, fleet=[], tasks=[])
    calls = []
    adapter = CuOptAdapter(settings=None,
                           transport=lambda r: calls.append(r) or {})
    sol = adapter.solve(p)
    assert calls == []                 # no network when there's nothing to solve
    assert sol.routes == {}
    assert sol.dropped == []
    assert sol.feasible is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_cuopt_adapter.py -v`
Expected: FAIL — `ImportError: cannot import name 'CuOptAdapter'`.

- [ ] **Step 3: Implement the adapter class**

Append to `fleet/routing/cuopt_adapter.py`:
```python
class CuOptAdapter:
    """RouteOptimizer backed by an NVIDIA cuOpt server.

    `transport(request_dict) -> response_dict` is injected so the solve path is
    testable offline. When omitted, a lazy default transport is built from
    `settings.cuopt_endpoint` on first use (requires the optional
    `cuopt-sh-client` package and a running cuOpt server / GPU)."""

    def __init__(self, settings=None,
                 transport: Callable[[dict], dict] = None):
        self.settings = settings
        self._transport = transport

    def solve(self, problem: RoutingProblem) -> RoutingSolution:
        if not problem.tasks or not problem.fleet:
            return RoutingSolution(
                routes={f.id: [] for f in problem.fleet},
                dropped=[t.customer_id for t in problem.tasks],
                feasible=True, metrics={"total_time_min": 0.0})

        base = _base_time(problem)
        request = to_cuopt_request(problem)
        response = self._get_transport()(request)
        return from_cuopt_response(problem, response, base)

    def _get_transport(self) -> Callable[[dict], dict]:
        if self._transport is None:
            self._transport = self._build_default_transport()
        return self._transport

    def _build_default_transport(self) -> Callable[[dict], dict]:
        """Lazily build the real cuOpt transport from settings. Imported here so
        the dependency is optional and tests never touch the network."""
        endpoint = getattr(self.settings, "cuopt_endpoint", "") or ""
        if not endpoint:
            raise RuntimeError(
                "CuOptAdapter has no transport and settings.cuopt_endpoint is "
                "empty; configure a cuOpt server or inject a transport.")

        from cuopt_sh_client import CuOptServiceSelfHostClient  # optional dep

        # endpoint formatted as "host:port" (e.g. "localhost:5000")
        host, _, port = endpoint.partition(":")
        client = CuOptServiceSelfHostClient(ip=host or "localhost",
                                            port=int(port or "5000"))

        def transport(request: dict) -> dict:
            return client.get_optimized_routes(request)

        return transport
```

> Note: depending on the installed `cuopt-sh-client` version, `get_optimized_routes` may return either the full envelope (`{"response": {...}}`) or just the `response` body. `from_cuopt_response` expects the full envelope; if your client returns the inner body, wrap it: `return {"response": client.get_optimized_routes(request)}`. This only affects the live transport, which tests do not exercise.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_cuopt_adapter.py -v`
Expected: PASS (all adapter tests).

- [ ] **Step 5: Commit**

```
git add fleet/routing/cuopt_adapter.py tests/test_cuopt_adapter.py
git commit -m "feat(routing): CuOptAdapter.solve with injected transport

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Factory selection + document optional dependency

**Files:**
- Modify: `fleet/factory.py`
- Modify: `requirements.txt`
- Test: `tests/test_factory.py` (create if it does not exist)

- [ ] **Step 1: Write the failing test**

`tests/test_factory.py` already exists (it has `test_cpu_and_rule_are_the_defaults` covering the CPU default — do NOT duplicate it). Add the import for `CuOptAdapter` to the existing import block:
```python
from fleet.routing.cuopt_adapter import CuOptAdapter
```
and append these two new tests:
```python
def test_cuopt_engine_with_endpoint_selects_cuopt_adapter():
    s = load_settings(env={"ROUTING_ENGINE": "cuopt",
                           "CUOPT_ENDPOINT": "localhost:5000"})
    comps = build_components(s)
    assert isinstance(comps.optimizer, CuOptAdapter)


def test_cuopt_engine_without_endpoint_falls_back_to_cpu():
    s = load_settings(env={"ROUTING_ENGINE": "cuopt", "CUOPT_ENDPOINT": ""})
    comps = build_components(s)
    assert isinstance(comps.optimizer, CpuSolver)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_factory.py -v`
Expected: FAIL — `test_cuopt_engine_with_endpoint_selects_cuopt_adapter` fails (factory still returns `CpuSolver` for `cuopt`).

- [ ] **Step 3: Wire the factory**

In `fleet/factory.py`, add the import:
```python
from fleet.routing.cuopt_adapter import CuOptAdapter
```
Replace the routing-engine block:
```python
    # Routing engine. cuOpt (GPU) when requested AND an endpoint is configured;
    # otherwise fall back to the CPU OR-Tools solver so the system always runs.
    if settings.routing_engine == "cuopt" and getattr(
            settings, "cuopt_endpoint", ""):
        optimizer: RouteOptimizer = CuOptAdapter(settings)
    else:
        optimizer = CpuSolver(settings)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_factory.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Document the optional dependency**

In `requirements.txt`, append (a comment — do NOT hard-require it, since it needs a GPU/server):
```
# Optional (M4, GPU): NVIDIA cuOpt self-hosted thin client. Only needed when
# ROUTING_ENGINE=cuopt with a live cuOpt server. The CPU solver (ortools) is the
# default and the test suite never imports this.
# cuopt-sh-client
```

- [ ] **Step 6: Full suite + smoke run**

Run: `pytest -v` (expect all green — prior count plus the new cuOpt/factory tests).
Run: `python -m fleet.loop` (still uses the CPU solver by default; should run clean).

- [ ] **Step 7: Commit**

```
git add fleet/factory.py tests/test_factory.py requirements.txt
git commit -m "feat(factory): select CuOptAdapter for ROUTING_ENGINE=cuopt (CPU fallback)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification checklist (end of plan)

- [ ] `pytest -v` fully green.
- [ ] `to_cuopt_request` produces the documented cuOpt JSON shape (matrices keyed by veh_type int, demand/capacities as `[n_dims][n]`, int minutes-from-base time windows, priority-scaled penalties).
- [ ] `from_cuopt_response` maps `vehicle_data` → per-vehicle `SolvedStop`s (correct customer ids, arrival/departure, reconstructed `load_after`), `dropped_tasks` → `dropped`, non-zero `status` → `feasible=False`.
- [ ] `CuOptAdapter.solve` round-trips through an injected transport and short-circuits empty problems without calling it.
- [ ] Factory returns `CuOptAdapter` only when `ROUTING_ENGINE=cuopt` **and** `CUOPT_ENDPOINT` is set; otherwise `CpuSolver`.
- [ ] Test suite never imports `cuopt-sh-client`; it is documented as optional in `requirements.txt`.
- [ ] Only the files named in each task were committed (no `Guide.md`/`problem.txt`/`docs/PROBLEM_STATEMENT.md`).

**Completes M4.** Next milestone: **M5 — ClaudeAgent behind the `DecisionEngine` interface** (LLM-driven decisions plug in beside `RuleBasedEngine`, selected by `config/settings.py`; default stays rule-based with no API key).
