# M3 (part 1) — Routing Matrix & Problem Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `WorldState` road graph into the inputs a VRPTW solver needs — per-`veh_type` travel-time matrices computed by flood/blocked-aware Dijkstra over the multi-edge graph, plus a `RoutingProblem` assembled from depot/vehicles/customer-orders.

**Architecture:** `fleet/routing/matrix.py` gets three pure functions: `shortest_times_from` (Dijkstra from one node, honoring `RoadEdge.is_passable` and `effective_time`, picking the min among parallel edges), `build_time_matrix` (N×N matrix over a location list for a given wade capability), and `build_routing_problem` (groups vehicles by `veh_type`, builds one matrix per type, and emits `RoutingProblem` with fleet + tasks). No solver yet, no new dependency — this is the deterministic, testable substrate the OR-Tools `CpuSolver` consumes in M3 part 2.

**Tech Stack:** Python 3.10+, `heapq` (stdlib Dijkstra), dataclasses, pytest. Same repo/venv/branch.

---

## Context

- Continues branch **`feat/base-project`** (plans 1–3 executed & green).
- **Depends on the multiple-edges amendment (executed):** uses `RoadGraph.out_edges`, `RoadEdge.is_passable`, `RoadEdge.effective_time`, and the sample's parallel flood-prone `DEPOT->C001#2` edge.
- **M3 is split into three plans:** (1) **this** — matrix + problem builder; (2) `CpuSolver` via Google OR-Tools (VRPTW: capacity + time windows + node-dropping disjunctions + per-veh_type transit) + loop initial-planning; (3) vehicle movement along solved routes + reroute (edge-status change → matrix update → re-solve). This plan adds **no** dependency; OR-Tools arrives in part 2.
- New file: `fleet/routing/matrix.py`. New tests: `tests/test_matrix.py`, `tests/test_routing_problem.py`. No existing files change.

**Modeling choices locked here** (documented in code, refinable later):
- `service_time_min` is a constant `DEFAULT_SERVICE_TIME_MIN = 10.0` (the contract has no per-customer service time yet).
- `demand_kg` = total order units per customer (1 unit ≈ 1 kg; per-SKU weights are a future refinement).
- Per `veh_type`, the matrix uses the **minimum** `wade_capability` among that type's vehicles (conservative: an edge must be passable by every vehicle of the type).
- Depot graph node id is `"DEPOT"` (matches `build_sample_state`).
- Unreachable pairs → `INF` (`float("inf")`); the solver will drop/penalize them in part 2.

Environment reminder (Windows / PowerShell): activate venv `.\.venv\Scripts\Activate.ps1`; run tests `pytest -v`; commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Only `git add` the files named in each task.

---

### Task 1: Dijkstra over the multi-edge, flood/blocked-aware graph

**Files:**
- Create: `fleet/routing/matrix.py`
- Test: `tests/test_matrix.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_matrix.py`:
```python
from fleet.contracts.state import RoadGraph, RoadNode, RoadEdge, Location, EdgeStatus
from fleet.routing.matrix import shortest_times_from, INF


def _graph(edges):
    """Build a RoadGraph from a list of RoadEdge (nodes + adjacency inferred)."""
    nodes, adjacency, edict = {}, {}, {}
    for e in edges:
        for n in (e.from_node, e.to_node):
            nodes.setdefault(n, RoadNode(n, Location(0, 0, "", n)))
            adjacency.setdefault(n, [])
        edict[e.id] = e
        adjacency[e.from_node].append(e.id)
    return RoadGraph(nodes=nodes, edges=edict, adjacency=adjacency)


def test_dijkstra_simple_path():
    g = _graph([RoadEdge("A", "B", 1, 10), RoadEdge("B", "C", 1, 5)])
    dist = shortest_times_from(g, "A", wade_capability=1.0)
    assert dist["A"] == 0.0
    assert dist["B"] == 10.0
    assert dist["C"] == 15.0


def test_dijkstra_picks_min_parallel_edge():
    g = _graph([
        RoadEdge("A", "B", 2, 10),
        RoadEdge("A", "B", 1, 6, id="A->B#2"),
    ])
    assert shortest_times_from(g, "A", 1.0)["B"] == 6.0


def test_dijkstra_excludes_flooded_edge_for_low_wade():
    g = _graph([
        RoadEdge("A", "B", 2, 10),
        RoadEdge("A", "B", 1, 6, id="A->B#2",
                 status=EdgeStatus.FLOODED, flood_level=0.5),
    ])
    assert shortest_times_from(g, "A", 0.3)["B"] == 10.0   # cannot wade -> slow route
    assert shortest_times_from(g, "A", 0.6)["B"] == 6.0    # can wade -> fast route


def test_dijkstra_excludes_blocked_edge_for_all():
    g = _graph([RoadEdge("A", "B", 1, 5, status=EdgeStatus.BLOCKED)])
    assert shortest_times_from(g, "A", 99.0).get("B", INF) == INF


def test_dijkstra_uses_traffic_factor_in_weight():
    g = _graph([RoadEdge("A", "B", 1, 10, traffic_factor=3.0)])
    assert shortest_times_from(g, "A", 1.0)["B"] == 30.0


def test_dijkstra_unreachable_node_absent():
    g = _graph([RoadEdge("A", "B", 1, 5)])
    assert "Z" not in shortest_times_from(g, "A", 1.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_matrix.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.routing.matrix'`.

- [ ] **Step 3: Create `fleet/routing/matrix.py` with Dijkstra**

```python
"""Travel-time matrices for routing.

Dijkstra over the (directed, multi-edge) road graph using each edge's
`effective_time` as weight and `is_passable(wade_capability)` to skip
flooded/blocked edges. Parallel edges A->B are handled naturally: relaxing all
outgoing edges keeps the minimum. Pure + deterministic; no solver here."""

import heapq
from typing import Dict, List

from fleet.contracts.state import RoadGraph

INF = float("inf")


def shortest_times_from(graph: RoadGraph, source: str,
                        wade_capability: float) -> Dict[str, float]:
    """Min travel time (minutes) from `source` to every reachable node, for a
    vehicle that can wade up to `wade_capability` metres. Unreachable nodes are
    absent from the result."""
    dist: Dict[str, float] = {source: 0.0}
    pq: List = [(0.0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, INF):
            continue
        for edge in graph.out_edges(u):
            if not edge.is_passable(wade_capability):
                continue
            nd = d + edge.effective_time
            if nd < dist.get(edge.to_node, INF):
                dist[edge.to_node] = nd
                heapq.heappush(pq, (nd, edge.to_node))
    return dist
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_matrix.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```powershell
git add fleet/routing/matrix.py tests/test_matrix.py
git commit -m "feat(routing): Dijkstra shortest times (flood/blocked/parallel-edge aware)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: N×N time matrix over a location list

**Files:**
- Modify: `fleet/routing/matrix.py` (append `build_time_matrix`)
- Test: `tests/test_matrix.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_matrix.py`:
```python
from fleet.routing.matrix import build_time_matrix
from fleet.scenarios import build_sample_state

_SAMPLE_LOCS = ["DEPOT", "C001", "C002", "C003", "C004"]


def test_matrix_diagonal_zero_and_directed():
    g = _graph([RoadEdge("A", "B", 1, 10)])   # only A->B
    m = build_time_matrix(g, ["A", "B"], 1.0)
    assert m[0][0] == 0.0 and m[1][1] == 0.0
    assert m[0][1] == 10.0      # A->B
    assert m[1][0] == INF       # no B->A edge


def test_matrix_on_sample_excludes_flood_route_for_truck():
    m = build_time_matrix(build_sample_state().road_graph, _SAMPLE_LOCS, 0.3)
    # flooded DEPOT->C001#2 (6 min) impassable for wade 0.3 -> use the 10-min edge
    assert m[0][1] == 10.0


def test_matrix_on_sample_uses_flood_shortcut_for_amphibious():
    m = build_time_matrix(build_sample_state().road_graph, _SAMPLE_LOCS, 0.6)
    assert m[0][1] == 6.0       # can wade -> faster flooded shortcut
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_matrix.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_time_matrix'`.

- [ ] **Step 3: Append `build_time_matrix` to `fleet/routing/matrix.py`**

```python
def build_time_matrix(graph: RoadGraph, locations: List[str],
                      wade_capability: float) -> List[List[float]]:
    """N×N travel-time matrix (minutes) over `locations`, indexed by position in
    the list. `matrix[i][j]` = shortest time from locations[i] to locations[j]
    for a vehicle of the given wade capability; INF if unreachable."""
    n = len(locations)
    pos = {loc: i for i, loc in enumerate(locations)}
    matrix = [[INF] * n for _ in range(n)]
    for i, src in enumerate(locations):
        matrix[i][i] = 0.0
        for loc, t in shortest_times_from(graph, src, wade_capability).items():
            if loc in pos:
                matrix[i][pos[loc]] = t
    return matrix
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_matrix.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```powershell
git add fleet/routing/matrix.py tests/test_matrix.py
git commit -m "feat(routing): build_time_matrix (per-wade N×N travel times)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `build_routing_problem` (WorldState → RoutingProblem)

**Files:**
- Modify: `fleet/routing/matrix.py` (imports + constant + `build_routing_problem`)
- Test: `tests/test_routing_problem.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_routing_problem.py`:
```python
from fleet.routing.matrix import build_routing_problem, DEFAULT_SERVICE_TIME_MIN
from fleet.scenarios import build_sample_state


def test_problem_locations_depot_first():
    p = build_routing_problem(build_sample_state())
    assert p.depot_id == "DEPOT"
    assert p.locations[0] == "DEPOT"
    assert set(p.locations[1:]) == {"C001", "C002", "C003", "C004"}


def test_problem_has_truck_matrix_flood_aware():
    p = build_routing_problem(build_sample_state())
    assert "truck" in p.time_matrix
    di, ci = p.locations.index("DEPOT"), p.locations.index("C001")
    assert p.time_matrix["truck"][di][ci] == 10.0   # flood shortcut excluded (wade 0.3)


def test_problem_fleet_and_tasks():
    p = build_routing_problem(build_sample_state())
    assert len(p.fleet) == 3
    assert all(f.capacity_kg == 500 for f in p.fleet)
    assert {t.customer_id for t in p.tasks} == {"C001", "C002", "C003", "C004"}
    t001 = next(t for t in p.tasks if t.customer_id == "C001")
    assert t001.demand_kg == 15.0          # SKU001:10 + SKU002:5
    assert t001.service_time_min == DEFAULT_SERVICE_TIME_MIN
    assert t001.priority == 1


def test_problem_skips_customers_without_orders():
    s = build_sample_state()
    s.customers["C002"].orders.clear()
    p = build_routing_problem(s)
    assert "C002" not in p.locations
    assert all(t.customer_id != "C002" for t in p.tasks)


def test_problem_separate_matrix_per_vehicle_type():
    s = build_sample_state()
    s.vehicles["V001"].veh_type = "amphibious"
    s.vehicles["V001"].wade_capability = 0.6
    p = build_routing_problem(s)
    assert set(p.time_matrix.keys()) == {"truck", "amphibious"}
    di, ci = p.locations.index("DEPOT"), p.locations.index("C001")
    assert p.time_matrix["truck"][di][ci] == 10.0       # wade 0.3
    assert p.time_matrix["amphibious"][di][ci] == 6.0   # wade 0.6 -> flood shortcut
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_routing_problem.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_routing_problem'`.

- [ ] **Step 3: Extend imports in `fleet/routing/matrix.py`**

Replace the import block:
```python
import heapq
from typing import Dict, List

from fleet.contracts.state import RoadGraph
```
with:
```python
import heapq
from typing import Dict, List

from fleet.contracts.state import RoadGraph, WorldState
from fleet.contracts.dto import RoutingProblem, FleetVehicleSpec, TaskSpec

DEFAULT_SERVICE_TIME_MIN = 10.0   # per-stop service time (no per-customer field yet)
```

- [ ] **Step 4: Append `build_routing_problem` to `fleet/routing/matrix.py`**

```python
def build_routing_problem(state: WorldState,
                          depot_id: str = "DEPOT") -> RoutingProblem:
    """Assemble a solver-ready RoutingProblem from the current world.

    - locations: depot first, then customers that still have pending orders.
    - time_matrix: one N×N matrix per veh_type, using the minimum wade_capability
      among that type's vehicles (conservative: passable by every such vehicle).
    - fleet: one FleetVehicleSpec per vehicle (shift falls back to depot hours).
    - tasks: one TaskSpec per pending customer (demand_kg = total order units).
    """
    pending = [cid for cid in sorted(state.customers)
               if sum(state.customers[cid].orders.values()) > 0]
    locations = [depot_id] + pending

    by_type: Dict[str, list] = {}
    for v in state.vehicles.values():
        by_type.setdefault(v.veh_type, []).append(v)
    time_matrix = {
        vt: build_time_matrix(state.road_graph, locations,
                              min(v.wade_capability for v in vs))
        for vt, vs in by_type.items()
    }

    fleet = [
        FleetVehicleSpec(
            id=v.id, capacity_kg=v.capacity_kg, veh_type=v.veh_type,
            shift_start=v.shift_start or state.depot.opening_time,
            shift_end=v.shift_end or state.depot.closing_time,
        )
        for v in state.vehicles.values()
    ]

    tasks = []
    for cid in pending:
        c = state.customers[cid]
        tasks.append(TaskSpec(
            customer_id=cid,
            demand_kg=float(sum(c.orders.values())),
            tw_start=c.time_window.start, tw_end=c.time_window.end,
            service_time_min=DEFAULT_SERVICE_TIME_MIN,
            priority=c.priority,
        ))

    return RoutingProblem(locations=locations, depot_id=depot_id,
                          time_matrix=time_matrix, fleet=fleet, tasks=tasks)
```

- [ ] **Step 5: Run to verify pass + full suite green**

Run: `pytest -q`
Expected: PASS (all tests, including the new routing-problem tests).

- [ ] **Step 6: Commit**

```powershell
git add fleet/routing/matrix.py tests/test_routing_problem.py
git commit -m "feat(routing): build_routing_problem (per-veh_type matrices, fleet, tasks)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Definition of done

- `pytest -q` green; `test_matrix.py` proves Dijkstra correctness, parallel-edge minimum, flood/blocked exclusion, traffic-factor weighting; `test_routing_problem.py` proves depot-first locations, per-veh_type flood-aware matrices, fleet/tasks assembly, order-less customers skipped.
- `build_routing_problem(state)` returns a `RoutingProblem` ready for any `RouteOptimizer.solve()` — the same DTO the CPU and cuOpt solvers consume.
- No new dependency; everything pure and deterministic.

**Next plan: M3 part 2 — `CpuSolver` via Google OR-Tools** (replaces the stub). Already-gathered API plan:
- `pywrapcp.RoutingIndexManager(len(locations), len(fleet), depot_index)` + `RoutingModel`.
- **Per-veh_type travel time:** register one transit callback per `veh_type` (reads `problem.time_matrix[vt]`), assign to each vehicle via `SetArcCostEvaluatorOfVehicle`, and build the `"Time"` dimension with `AddDimensionWithVehicleTransits([...])`; add `service_time_min` into the transit (service at `from` node).
- **Time windows:** `time_dimension.CumulVar(index).SetRange(tw_start, tw_end)` per task node and per vehicle start (depot/shift).
- **Capacity:** unary demand callback + `AddDimensionWithVehicleCapacity(demand_idx, 0, [capacities], True, "Capacity")` (hard, spec §6.9).
- **Node dropping → `dropped`/DEFER:** `AddDisjunction([node_index], penalty)` per task (penalty scaled by priority so urgent orders are kept); read drops via `solution.Value(routing.NextVar(node)) == node`.
- **Determinism for tests:** default `FirstSolutionStrategy.PATH_CHEAPEST_ARC` with no metaheuristic/time-limit (instant, deterministic); expose an optional `GUIDED_LOCAL_SEARCH` + time-limit knob (new setting) for demo quality. Convert datetimes to integer minutes-from-day-start for the solver, back to datetimes for `RoutingSolution`.
- Add `ortools` to `requirements.txt`; map output to `RoutingSolution(routes, dropped, feasible, metrics)`.

Then M3 part 3: vehicle movement along solved routes + reroute (edge-status change → matrix recompute → re-solve).
