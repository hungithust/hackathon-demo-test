# RoadGraph Multiple Parallel Edges — Contract Amendment Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `RoadGraph` hold multiple parallel directed edges between the same node pair (A→B), because real road networks have them — resolving the §6.9 limitation flagged in plan 1.

**Architecture:** Give every `RoadEdge` a unique `id` (auto-derived `"{from}->{to}"`, explicit for parallels e.g. `"DEPOT->C001#2"`). Key `RoadGraph.edges` by `edge_id` instead of `(from, to)`. Make `adjacency` map a node to its outgoing edge ids, and add `out_edges` / `edges_between` / `get_edge` helpers that M3's Dijkstra and reroute will consume. Self-describing JSON serialization simplifies (no more tuple-keyed dict special case).

**Tech Stack:** Python 3.10+, dataclasses, pytest. Same repo/venv as plan 1.

---

## Context

- Continues branch **`feat/base-project`** (plan 1 — M0+M1 — already executed and green there).
- Triggered by an explicit decision: **multiple edges A→B is mandatory** (reality). Spec §6.9 always allowed it; the migrated contract (`edges: Dict[Tuple[str,str], RoadEdge]`) could not represent it. This plan makes the implementation match the spec.
- Lands **before M2 (simulator)** so the simulator and M3 (Dijkstra/matrix) build on the correct graph contract.
- **Backward-compat note:** `RoadEdge.id` is added with a default + `__post_init__` auto-derive, so existing positional `RoadEdge(...)` calls keep working and `test_state_schema.py` needs no changes. Only the `(from,to)`-keyed call sites change.

Environment reminder (Windows / PowerShell): activate venv `.\.venv\Scripts\Activate.ps1`; run tests `pytest -v`; commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Only `git add` the files named in each task.

---

### Task 1: Add `RoadEdge.id` (auto-derived, backward-compatible)

**Files:**
- Modify: `fleet/contracts/state.py` (the `RoadEdge` dataclass, currently lines 175–194)
- Test: `tests/test_state_schema.py` (append two tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state_schema.py`:
```python
def test_roadedge_id_auto_derives_from_endpoints():
    e = RoadEdge("DEPOT", "C001", 2.0, 10.0)
    assert e.id == "DEPOT->C001"


def test_roadedge_explicit_id_is_preserved():
    e = RoadEdge("DEPOT", "C001", 1.2, 6.0, id="DEPOT->C001#2")
    assert e.id == "DEPOT->C001#2"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_state_schema.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'id'` (and the auto-derive test errors on missing `.id`).

- [ ] **Step 3: Add the `id` field + `__post_init__`**

In `fleet/contracts/state.py`, replace the whole `RoadEdge` dataclass with:
```python
@dataclass
class RoadEdge:
    from_node: str
    to_node: str
    distance_km: float
    base_time_minutes: float
    traffic_factor: float = 1.0
    status: EdgeStatus = EdgeStatus.OPEN
    flood_level: float = 0.0       # flood depth (m); compared to Vehicle.wade_capability
    id: str = ""                   # unique edge id; auto-derived from endpoints if empty

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.from_node}->{self.to_node}"

    @property
    def effective_time(self) -> float:
        return self.base_time_minutes * self.traffic_factor

    def is_passable(self, wade_capability: float) -> bool:
        """Spec §6.5: BLOCKED forbidden for all; otherwise flooded edge is
        forbidden when its flood_level exceeds the vehicle's wade_capability."""
        if self.status == EdgeStatus.BLOCKED:
            return False
        return self.flood_level <= wade_capability
```

- [ ] **Step 4: Run to verify pass (and nothing else broke yet)**

Run: `pytest tests/test_state_schema.py tests/test_serialization.py -v`
Expected: PASS. (`RoadGraph` is still tuple-keyed at this point; `RoadEdge` now just carries an extra `id` that round-trips cleanly.)

- [ ] **Step 5: Commit**

```powershell
git add fleet/contracts/state.py tests/test_state_schema.py
git commit -m "feat(contracts): RoadEdge.id (auto-derived from endpoints)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Rekey `RoadGraph` by edge id + helpers + serialization cleanup

**Files:**
- Modify: `fleet/contracts/state.py` (`RoadGraph` dataclass lines 197–201; `_encode`/`_decode` lines ~286–322; `from typing import` line 11)
- Modify: `fleet/scenarios.py` (edge-building block, lines 66–72)
- Modify: `tests/test_serialization.py` (lines 26–30 and 53)
- Test: `tests/test_roadgraph.py` (new)

- [ ] **Step 1: Write the failing test for the new graph API**

Create `tests/test_roadgraph.py`:
```python
from datetime import datetime

from fleet.contracts.state import (
    RoadGraph, RoadNode, RoadEdge, Location, EdgeStatus, WorldState, Depot,
)


def _two_node_graph():
    a = Location(0.0, 0.0, "", "A")
    b = Location(1.0, 1.0, "", "B")
    e1 = RoadEdge("A", "B", 2.0, 10.0)                       # id -> "A->B"
    e2 = RoadEdge("A", "B", 1.5, 7.0, id="A->B#2",
                  status=EdgeStatus.FLOODED, flood_level=0.5)
    graph = RoadGraph(
        nodes={"A": RoadNode("A", a), "B": RoadNode("B", b)},
        edges={e1.id: e1, e2.id: e2},
        adjacency={"A": ["A->B", "A->B#2"], "B": []},
    )
    return graph, e1, e2


def test_parallel_edges_between_same_pair():
    graph, e1, e2 = _two_node_graph()
    between = graph.edges_between("A", "B")
    assert len(between) == 2
    assert {e.id for e in between} == {"A->B", "A->B#2"}


def test_out_edges_uses_adjacency_index():
    graph, e1, e2 = _two_node_graph()
    assert {e.id for e in graph.out_edges("A")} == {"A->B", "A->B#2"}
    assert graph.out_edges("B") == []


def test_get_edge_by_id():
    graph, e1, e2 = _two_node_graph()
    assert graph.get_edge("A->B#2") is e2
    assert graph.get_edge("does-not-exist") is None


def test_round_trip_preserves_parallel_edges():
    graph, _e1, _e2 = _two_node_graph()
    t0 = datetime(2026, 6, 5, 6, 0)
    state = WorldState(clock=t0,
                       depot=Depot(Location(0, 0, "", "d"), {}, t0, t0),
                       road_graph=graph)
    snapshot = state.to_dict()
    restored = WorldState.from_dict(snapshot)
    assert restored.to_dict() == snapshot
    assert len(restored.road_graph.edges_between("A", "B")) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_roadgraph.py -v`
Expected: FAIL — `AttributeError: 'RoadGraph' object has no attribute 'edges_between'`.

- [ ] **Step 3: Rekey `RoadGraph` and add helpers**

In `fleet/contracts/state.py`, replace the `RoadGraph` dataclass with:
```python
@dataclass
class RoadGraph:
    nodes: Dict[str, RoadNode]
    edges: Dict[str, RoadEdge]                # edge_id -> edge (supports parallel A->B)
    adjacency: Dict[str, List[str]] = field(default_factory=dict)
    # adjacency[node_id] = ids of edges whose from_node == node_id (outgoing)

    def get_edge(self, edge_id: str) -> Optional["RoadEdge"]:
        return self.edges.get(edge_id)

    def out_edges(self, node_id: str) -> List["RoadEdge"]:
        return [self.edges[eid] for eid in self.adjacency.get(node_id, [])
                if eid in self.edges]

    def edges_between(self, from_node: str, to_node: str) -> List["RoadEdge"]:
        return [e for e in self.out_edges(from_node) if e.to_node == to_node]
```

- [ ] **Step 4: Drop the unused `Tuple` import**

In `fleet/contracts/state.py`, change line 11 from:
```python
from typing import Dict, List, Optional, Tuple
```
to:
```python
from typing import Dict, List, Optional
```

- [ ] **Step 5: Remove the tuple-key special case from serialization**

In `fleet/contracts/state.py`, in `_encode`, replace the `dict` branch:
```python
    if isinstance(obj, dict):
        if obj and all(isinstance(k, tuple) for k in obj):  # RoadGraph.edges
            return {"__tuplekeys__": [[list(k), _encode(v)] for k, v in obj.items()]}
        return {k: _encode(v) for k, v in obj.items()}
```
with:
```python
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
```
And in `_decode`, delete these two lines:
```python
        if "__tuplekeys__" in obj:
            return {tuple(k): _decode(v) for k, v in obj["__tuplekeys__"]}
```

- [ ] **Step 6: Run the new graph test (it should pass now)**

Run: `pytest tests/test_roadgraph.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Run the full suite to see what the rekey broke**

Run: `pytest -q`
Expected: FAIL in `tests/test_serialization.py` (tuple-keyed `edges`) and possibly `tests/test_scenarios.py` (round-trip / build). These get fixed in the next two steps.

- [ ] **Step 8: Fix `scenarios.py` to build edges keyed by id**

In `fleet/scenarios.py`, replace the edge-building block (currently lines 66–72):
```python
    edges = {}
    adjacency = {n: [] for n in nodes}
    for a, b, km, mins in edge_list:
        edges[(a, b)] = RoadEdge(a, b, km, mins)
        edges[(b, a)] = RoadEdge(b, a, km, mins)
        adjacency[a].append(b)
        adjacency[b].append(a)
```
with:
```python
    edges = {}
    adjacency = {n: [] for n in nodes}

    def _add_edge(a, b, km, mins, **kw):
        e = RoadEdge(a, b, km, mins, **kw)
        edges[e.id] = e
        adjacency[a].append(e.id)

    for a, b, km, mins in edge_list:
        _add_edge(a, b, km, mins)
        _add_edge(b, a, km, mins)
```

- [ ] **Step 9: Fix `test_serialization.py` to key edges by id**

In `tests/test_serialization.py`, replace the `road_graph=RoadGraph(...)` block (lines 26–30):
```python
        road_graph=RoadGraph(
            nodes={"DEPOT": RoadNode("DEPOT", loc_d), "C1": RoadNode("C1", loc_c)},
            edges={("DEPOT", "C1"): RoadEdge("DEPOT", "C1", 2.0, 10.0,
                                             status=EdgeStatus.FLOODED, flood_level=0.4)},
            adjacency={"DEPOT": ["C1"]}),
```
with:
```python
        road_graph=RoadGraph(
            nodes={"DEPOT": RoadNode("DEPOT", loc_d), "C1": RoadNode("C1", loc_c)},
            edges={"DEPOT->C1": RoadEdge("DEPOT", "C1", 2.0, 10.0,
                                         status=EdgeStatus.FLOODED, flood_level=0.4)},
            adjacency={"DEPOT": ["DEPOT->C1"]}),
```
And replace line 53:
```python
    edge = restored.road_graph.edges[("DEPOT", "C1")]
```
with:
```python
    edge = restored.road_graph.get_edge("DEPOT->C1")
```

- [ ] **Step 10: Run the full suite (should be green)**

Run: `pytest -q`
Expected: PASS (all tests, including `test_roadgraph.py`, `test_serialization.py`, `test_scenarios.py`).

- [ ] **Step 11: Commit**

```powershell
git add fleet/contracts/state.py fleet/scenarios.py tests/test_serialization.py tests/test_roadgraph.py
git commit -m "feat(contracts): key RoadGraph by edge id; out_edges/edges_between/get_edge helpers" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Put a real parallel edge in the sample world

**Files:**
- Modify: `fleet/scenarios.py` (import line + add two edges after the main loop)
- Test: `tests/test_scenarios.py` (append one test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scenarios.py`:
```python
def test_sample_has_parallel_edges_depot_to_c001():
    s = build_sample_state()
    parallels = s.road_graph.edges_between("DEPOT", "C001")
    assert len(parallels) == 2
    assert {e.id for e in parallels} == {"DEPOT->C001", "DEPOT->C001#2"}
    # the shortcut floods deeper than a standard truck (wade 0.3 m) can pass
    shortcut = s.road_graph.get_edge("DEPOT->C001#2")
    assert shortcut.is_passable(0.3) is False
    assert shortcut.is_passable(0.6) is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_scenarios.py::test_sample_has_parallel_edges_depot_to_c001 -v`
Expected: FAIL — only one edge between DEPOT and C001 (`assert 1 == 2`).

- [ ] **Step 3: Add `EdgeStatus` to the scenarios import**

In `fleet/scenarios.py`, change the import block:
```python
from fleet.contracts.state import (
    WorldState, Depot, Location, Vehicle, VehicleStatus, CustomerProfile,
    TimeWindow, RoadGraph, RoadNode, RoadEdge,
)
```
to:
```python
from fleet.contracts.state import (
    WorldState, Depot, Location, Vehicle, VehicleStatus, CustomerProfile,
    TimeWindow, RoadGraph, RoadNode, RoadEdge, EdgeStatus,
)
```

- [ ] **Step 4: Add the parallel edge after the main edge loop**

In `fleet/scenarios.py`, immediately after the `for a, b, km, mins in edge_list:` loop (the two `_add_edge` calls), add:
```python
    # A second, shorter DEPOT<->C001 route that floods in the rainy season:
    # a realistic parallel edge (spec §6.9). Standard trucks (wade 0.3 m) cannot
    # use it while flooded — this is exactly what M3's per-veh_type matrix exploits.
    _add_edge("DEPOT", "C001", 1.2, 6.0, id="DEPOT->C001#2",
              status=EdgeStatus.FLOODED, flood_level=0.5)
    _add_edge("C001", "DEPOT", 1.2, 6.0, id="C001->DEPOT#2",
              status=EdgeStatus.FLOODED, flood_level=0.5)
```

- [ ] **Step 5: Run to verify pass + full suite green**

Run: `pytest -q`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```powershell
git add fleet/scenarios.py tests/test_scenarios.py
git commit -m "feat(scenarios): parallel flood-prone DEPOT<->C001 route (multiple edges)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Definition of done

- `pytest -q` green; `tests/test_roadgraph.py` proves parallel edges, helpers, and round-trip with parallels.
- `RoadGraph.edges` is keyed by `edge_id`; `adjacency` indexes outgoing edge ids; `get_edge` / `out_edges` / `edges_between` available for M3.
- Sample world contains a genuine parallel `DEPOT↔C001` route (one floods), so multiple-edges is exercised, not just supported.
- `__tuplekeys__` serialization special case removed; `Tuple` import gone from `state.py`.

**Next plan: M2 — real Simulator.** One design question to settle when we start it: M2 moves vehicles, but realistic movement needs shortest-path (which is M3's `matrix.py`). Likely answer: M2 uses a simplified movement model (advance toward the next planned stop by edge `effective_time`), and M3 swaps in the matrix. We'll confirm before writing M2.
