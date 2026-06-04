# Fleet Optimizer — Walking Skeleton (M0 + M1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the base-project foundation — a stable contract/interface layer plus a headless end-to-end loop (simulator → detection → decision → approval → dispatch → audit) running with minimal stub implementations.

**Architecture:** A dependency-free `fleet/contracts/` layer (WorldState entities + 6 `Protocol` interfaces + routing DTOs). Every module hides behind an interface with a default stub impl chosen by `config/settings.py` via a factory. `fleet/loop.py` wires them and runs headless. Later milestones (M2–M7) replace each stub with a real impl without touching callers.

**Tech Stack:** Python 3.10+, dataclasses, `typing.Protocol` (runtime_checkable), pytest. No GPU, no API key, no DB required for this plan.

---

## Plan series & scope

This is **plan 1 of a series**. It covers spec milestones **M0 (foundation)** and **M1 (walking skeleton)** from `docs/superpowers/specs/2026-06-04-fleet-optimizer-base-project-spec.md`.

Follow-up plans (one each, written later) deepen modules behind the now-stable interfaces:
- **M2** — real Simulator (demand seasonality+noise, vehicle movement, inventory/restock)
- **M3** — `CpuSolver` (greedy VRPTW) + `matrix.py` (Dijkstra); reroute = re-solve
- **M4** — `CuOptAdapter` (config switch + GPU fallback)
- **M5** — `ClaudeAgent` (ReAct + tool-calling)
- **M6** — `EwmaForecaster` + `ZScoreDetector`
- **M7** — Streamlit UI

**`MOPHONG_Hackathon/` handling:** kept only as the migration source for `state.py` and the sample builder. **Deleted in Task 8** (end of M0), after the migration is proven green. It is git-untracked, so deletion is permanent — that is intentional and approved; everything of value is migrated into `fleet/` first.

**Schema decisions applied during migration** (spec §6, ⚠️ = change vs teammate code):
- ⚠️ §6.1 Priority = 4 levels, **1 = most urgent → 4 = least**; add `PriorityLevel(IntEnum)`; `CustomerProfile.priority` default → 4.
- ⚠️ §6.5 FLOODED per vehicle: add `RoadEdge.flood_level`, `Vehicle.wade_capability`, `Vehicle.veh_type`; add `RoadEdge.is_passable(wade_capability)` (BLOCKED forbidden for all; `flood_level > wade_capability` forbidden for that vehicle).
- §6.9 (Q&A) add `Event.ended_at`; fix `get_active_events()` to filter `ended_at is None`.
- §6.10 implement `to_dict`/`from_dict` (currently TODO stubs).
- §6.6 approval policy (`should_auto_approve`) — implemented in M1.

**Known deferrals (spec items whose *logic* lands in later milestones; M0/M1 only lays the contract groundwork):**
- §6.2 urgency_score / priority-vs-SLA tiebreak → solver+agent logic (M3/M5). `sla_critical_threshold_min` config is in place now.
- §6.3 late-delivery 2-phase (hard window at planning, late-KPI at execution) → solver (M3) + simulator KPI (M2). DTO already carries hard `tw_start/tw_end`.
- §6.4 severity computation → `RuleDetector` thresholds (M6). `Event.severity` field + `EventSeverity` enum in place.
- §6.7 standardized impact-metric keys → populated by real decision logic (M3/M5); `Decision.impact_estimate` is a free dict now.
- §6.8 inventory consumption/restock + `INVENTORY_SHORTAGE` events → real Simulator (M2).
- ⚠️ §6.9 "multiple edges A→B": the migrated contract keys edges by `(from, to)` (one edge per pair), so parallel edges are **not** representable as-is. Harmless for M0/M1 (sample graph has none). **Decision needed before M3** (Dijkstra/matrix): either keep one edge per pair (Dijkstra only needs the min-time edge anyway) or change `RoadGraph.edges` to `Dict[Tuple[str,str], List[RoadEdge]]`. Flagged, not resolved here.

---

# Milestone M0 — Foundation (contracts + scaffold)

### Task 1: Project scaffold (branch, package tree, tooling)

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `fleet/__init__.py`, `fleet/contracts/__init__.py`, `fleet/simulator/__init__.py`, `fleet/detection/__init__.py`, `fleet/routing/__init__.py`, `fleet/forecast/__init__.py`, `fleet/agent/__init__.py`, `fleet/dispatch/__init__.py`, `config/__init__.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Create the feature branch**

Run (PowerShell):
```powershell
git checkout -b feat/base-project
```
Expected: `Switched to a new branch 'feat/base-project'`

- [ ] **Step 2: Create `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
snapshots/
```

- [ ] **Step 3: Create `requirements.txt`**

```text
pytest>=7.4
```

- [ ] **Step 4: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "fleet-optimizer"
version = "0.1.0"
requires-python = ">=3.10"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **Step 5: Create empty package markers**

Create each of these as an empty file:
```
fleet/__init__.py
fleet/contracts/__init__.py
fleet/simulator/__init__.py
fleet/detection/__init__.py
fleet/routing/__init__.py
fleet/forecast/__init__.py
fleet/agent/__init__.py
fleet/dispatch/__init__.py
config/__init__.py
```

- [ ] **Step 6: Write the smoke test**

`tests/test_smoke.py`:
```python
def test_import_fleet():
    import fleet  # noqa: F401
```

- [ ] **Step 7: Create venv and install pytest**

Run (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
Expected: pytest installs without error.

- [ ] **Step 8: Run the smoke test**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS (1 passed)

- [ ] **Step 9: Commit**

```powershell
git add pyproject.toml requirements.txt .gitignore fleet config tests
git commit -m "chore: scaffold fleet base project (package tree, pytest)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Migrate `state.py` schema (with §6 fixes)

**Files:**
- Create: `fleet/contracts/state.py`
- Test: `tests/test_state_schema.py`

- [ ] **Step 1: Write the failing schema test**

`tests/test_state_schema.py`:
```python
from datetime import datetime, timedelta

from fleet.contracts.state import (
    PriorityLevel, CustomerProfile, Location, TimeWindow,
    RoadEdge, EdgeStatus, Vehicle, VehicleStatus, Event, EventType,
    EventSeverity, WorldState, Depot,
)


def test_priority_p1_is_most_urgent():
    assert PriorityLevel.P1.value == 1
    assert PriorityLevel.P4.value == 4
    assert PriorityLevel.P1 < PriorityLevel.P4  # IntEnum: 1 < 4


def test_customer_priority_default_is_least_urgent():
    c = CustomerProfile(
        id="C1", type="market",
        location=Location(10.0, 106.0, "addr", "name"),
        orders={"SKU1": 3},
        time_window=TimeWindow(datetime(2026, 6, 4, 8), datetime(2026, 6, 4, 12)),
    )
    assert c.priority == 4


def test_roadedge_effective_time():
    e = RoadEdge("A", "B", distance_km=2, base_time_minutes=10, traffic_factor=2.0)
    assert e.effective_time == 20.0


def test_blocked_edge_forbidden_for_all_vehicles():
    e = RoadEdge("A", "B", 1, 5, status=EdgeStatus.BLOCKED)
    assert e.is_passable(wade_capability=99.0) is False


def test_flood_level_vs_wade_capability():
    e = RoadEdge("A", "B", 1, 5, flood_level=0.4)
    assert e.is_passable(0.5) is True
    assert e.is_passable(0.3) is False


def test_vehicle_has_veh_type_and_wade_capability():
    v = Vehicle(id="V1", capacity_kg=500,
                pos=Location(0, 0, "", "depot"), current_load_kg=0)
    assert isinstance(v.veh_type, str) and v.veh_type
    assert v.wade_capability >= 0


def test_get_active_events_filters_ended():
    now = datetime(2026, 6, 4, 9)
    state = WorldState(
        clock=now,
        depot=Depot(location=Location(0, 0, "", "d"), inventory={},
                    opening_time=now, closing_time=now + timedelta(hours=8)),
    )
    live = Event(id="E1", event_type=EventType.TRAFFIC, target="A->B",
                 severity=EventSeverity.LOW, started_at=now)
    done = Event(id="E2", event_type=EventType.TRAFFIC, target="B->C",
                 severity=EventSeverity.LOW, started_at=now, ended_at=now)
    state.events.extend([live, done])
    active = state.get_active_events()
    assert [e.id for e in active] == ["E1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_state_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.contracts.state'`

- [ ] **Step 3: Write `fleet/contracts/state.py`**

```python
"""World State — shared contract for all modules (simulator, detection, agent, ui).

Migrated from MOPHONG_Hackathon/ai-fleet-optimizer/world_state_implementation.py
with spec §6 schema reconciliations applied (see plan header).
This module imports NOTHING from other fleet modules.
"""

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum, IntEnum
from typing import Dict, List, Optional, Tuple


# ============================================================================
# ENUMS
# ============================================================================

class VehicleStatus(str, Enum):
    AT_DEPOT = "at_depot"
    IN_TRANSIT = "in_transit"
    ON_ROUTE = "on_route"
    BROKEN = "broken"
    MAINTENANCE = "maintenance"


class EdgeStatus(str, Enum):
    OPEN = "open"
    CONGESTED = "congested"
    BLOCKED = "blocked"      # forbidden for ALL vehicles
    FLOODED = "flooded"      # passability depends on flood_level vs wade_capability


class EventType(str, Enum):
    TRAFFIC = "traffic"
    DEMAND_SURGE = "demand_surge"
    INVENTORY_SHORTAGE = "inventory_shortage"
    VEHICLE_BREAKDOWN = "vehicle_breakdown"
    URGENT_ORDER = "urgent_order"
    FLOODED_AREA = "flooded_area"


class EventSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionEngine(str, Enum):
    RULE_BASED = "rule_based"
    CLAUDE = "claude"
    HUMAN = "human"


class DecisionAction(str, Enum):
    REROUTE = "reroute"
    RESCHEDULE = "reschedule"
    REPRIORITIZE = "reprioritize"
    REALLOCATE = "reallocate"
    DEFER = "defer"
    CANCEL = "cancel"
    ACCELERATE = "accelerate"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDE = "override"


class PriorityLevel(IntEnum):
    """Customer priority. 1 = most urgent, 4 = least urgent (spec §6.1)."""
    P1 = 1
    P2 = 2
    P3 = 3
    P4 = 4


# ============================================================================
# ENTITIES
# ============================================================================

@dataclass
class Location:
    lat: float
    lng: float
    address: str
    name: str


@dataclass
class TimeWindow:
    start: datetime
    end: datetime

    def is_within(self, time: datetime) -> bool:
        return self.start <= time <= self.end


@dataclass
class Order:
    sku: str
    qty: int
    weight_kg: float = 1.0


@dataclass
class CustomerProfile:
    id: str
    type: str
    location: Location
    orders: Dict[str, int]
    time_window: TimeWindow
    priority: int = 4              # 1 = most urgent .. 4 = least urgent (see PriorityLevel)
    sla_deadline: Optional[datetime] = None
    contact_name: str = ""
    contact_phone: str = ""
    notes: str = ""


@dataclass
class Stop:
    customer_id: str
    sequence: int
    planned_arrival: datetime
    planned_departure: datetime
    actual_arrival: Optional[datetime] = None
    actual_departure: Optional[datetime] = None
    load_after_stop: float = 0.0


@dataclass
class VehicleRoute:
    vehicle_id: str
    stops: List[Stop]
    total_distance: float = 0.0
    total_time: float = 0.0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


@dataclass
class Vehicle:
    id: str
    capacity_kg: float
    pos: Location
    current_load_kg: float
    status: VehicleStatus = VehicleStatus.AT_DEPOT
    route: Optional[VehicleRoute] = None
    shift_start: Optional[datetime] = None
    shift_end: Optional[datetime] = None
    current_stop_index: int = -1
    mileage_km: float = 0.0
    fuel_level: float = 100.0
    veh_type: str = "truck"        # groups vehicles by wade_capability (spec §6.5)
    wade_capability: float = 0.3   # max flood depth (m) this vehicle can wade


@dataclass
class Depot:
    location: Location
    inventory: Dict[str, int]
    opening_time: datetime
    closing_time: datetime
    vehicles: List[Vehicle] = field(default_factory=list)


@dataclass
class RoadNode:
    id: str
    location: Location


@dataclass
class RoadEdge:
    from_node: str
    to_node: str
    distance_km: float
    base_time_minutes: float
    traffic_factor: float = 1.0
    status: EdgeStatus = EdgeStatus.OPEN
    flood_level: float = 0.0       # flood depth (m); compared to Vehicle.wade_capability

    @property
    def effective_time(self) -> float:
        return self.base_time_minutes * self.traffic_factor

    def is_passable(self, wade_capability: float) -> bool:
        """Spec §6.5: BLOCKED forbidden for all; otherwise flooded edge is
        forbidden when its flood_level exceeds the vehicle's wade_capability."""
        if self.status == EdgeStatus.BLOCKED:
            return False
        return self.flood_level <= wade_capability


@dataclass
class RoadGraph:
    nodes: Dict[str, RoadNode]
    edges: Dict[Tuple[str, str], RoadEdge]
    adjacency: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class Event:
    id: str
    event_type: EventType
    target: str
    severity: EventSeverity
    started_at: datetime
    description: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)
    ended_at: Optional[datetime] = None   # spec §6.9: event resolved when set


@dataclass
class Decision:
    id: str
    timestamp: datetime
    event_id: Optional[str]
    action: DecisionAction
    engine: DecisionEngine
    description: str
    impact_estimate: Dict[str, float] = field(default_factory=dict)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    execution_result: Optional[Dict] = None
    reasoning: str = ""


@dataclass
class WorldState:
    """Single in-memory source of truth. Snapshot to JSON via to_dict/from_dict."""

    clock: datetime
    depot: Depot
    customers: Dict[str, CustomerProfile] = field(default_factory=dict)
    vehicles: Dict[str, Vehicle] = field(default_factory=dict)
    road_graph: RoadGraph = field(
        default_factory=lambda: RoadGraph(nodes={}, edges={}, adjacency={}))
    plan: Dict[str, VehicleRoute] = field(default_factory=dict)
    events: List[Event] = field(default_factory=list)
    events_archive: List[Event] = field(default_factory=list)
    decisions: List[Decision] = field(default_factory=list)
    version: str = "2.0"
    sim_tick: int = 0

    # ----- helpers -----
    def get_customer(self, customer_id: str) -> Optional[CustomerProfile]:
        return self.customers.get(customer_id)

    def get_vehicle(self, vehicle_id: str) -> Optional[Vehicle]:
        return self.vehicles.get(vehicle_id)

    def get_route(self, vehicle_id: str) -> Optional[VehicleRoute]:
        return self.plan.get(vehicle_id)

    def get_active_events(self) -> List[Event]:
        return [e for e in self.events if e.ended_at is None]

    def get_pending_decisions(self) -> List[Decision]:
        return [d for d in self.decisions
                if d.approval_status == ApprovalStatus.PENDING]

    def get_approved_decisions(self) -> List[Decision]:
        return [d for d in self.decisions
                if d.approval_status == ApprovalStatus.APPROVED]

    def total_orders_pending(self) -> int:
        return sum(sum(c.orders.values()) for c in self.customers.values())

    def to_dict(self) -> dict:
        return _encode(self)

    @staticmethod
    def from_dict(data: dict) -> "WorldState":
        return _decode(data)


# ============================================================================
# SERIALIZATION (self-describing, generic; spec §6.10)
# ============================================================================

def _encode(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Enum):
        return {"__enum__": type(obj).__name__, "value": obj.value}
    if isinstance(obj, datetime):
        return {"__dt__": obj.isoformat()}
    if isinstance(obj, dict):
        if obj and all(isinstance(k, tuple) for k in obj):  # RoadGraph.edges
            return {"__tuplekeys__": [[list(k), _encode(v)] for k, v in obj.items()]}
        return {k: _encode(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode(v) for v in obj]
    if is_dataclass(obj):
        out = {"__type__": type(obj).__name__}
        for f in fields(obj):
            out[f.name] = _encode(getattr(obj, f.name))
        return out
    raise TypeError(f"Cannot encode {type(obj)!r}")


def _decode(obj):
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    if isinstance(obj, dict):
        if "__dt__" in obj:
            return datetime.fromisoformat(obj["__dt__"])
        if "__enum__" in obj:
            return _ENUM_REGISTRY[obj["__enum__"]](obj["value"])
        if "__tuplekeys__" in obj:
            return {tuple(k): _decode(v) for k, v in obj["__tuplekeys__"]}
        if "__type__" in obj:
            cls = _DATACLASS_REGISTRY[obj["__type__"]]
            kwargs = {k: _decode(v) for k, v in obj.items() if k != "__type__"}
            return cls(**kwargs)
        return {k: _decode(v) for k, v in obj.items()}
    return obj


_DATACLASS_REGISTRY = {c.__name__: c for c in [
    Location, TimeWindow, Order, CustomerProfile, Stop, VehicleRoute,
    Vehicle, Depot, RoadNode, RoadEdge, RoadGraph, Event, Decision, WorldState,
]}

_ENUM_REGISTRY = {c.__name__: c for c in [
    VehicleStatus, EdgeStatus, EventType, EventSeverity, DecisionEngine,
    DecisionAction, ApprovalStatus, PriorityLevel,
]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_state_schema.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/contracts/state.py tests/test_state_schema.py
git commit -m "feat(contracts): migrate WorldState schema with priority/flood/event fixes" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Round-trip serialization

**Files:**
- Modify: `fleet/contracts/state.py` (already has `to_dict`/`from_dict` + `_encode`/`_decode` from Task 2 — this task only adds the test that proves them)
- Test: `tests/test_serialization.py`

- [ ] **Step 1: Write the failing round-trip test**

`tests/test_serialization.py`:
```python
from datetime import datetime, timedelta

from fleet.contracts.state import (
    WorldState, Depot, Location, TimeWindow, CustomerProfile, Vehicle,
    VehicleStatus, RoadGraph, RoadNode, RoadEdge, EdgeStatus,
    Event, EventType, EventSeverity, Decision, DecisionAction, DecisionEngine,
)


def _small_state() -> WorldState:
    t0 = datetime(2026, 6, 4, 6, 0)
    loc_d = Location(10.82, 106.63, "depot addr", "Depot")
    loc_c = Location(10.80, 106.63, "cust addr", "BigC")
    state = WorldState(
        clock=t0,
        depot=Depot(location=loc_d, inventory={"SKU1": 100},
                    opening_time=t0, closing_time=t0 + timedelta(hours=12)),
        customers={"C1": CustomerProfile(
            id="C1", type="supermarket", location=loc_c,
            orders={"SKU1": 10},
            time_window=TimeWindow(t0 + timedelta(hours=1), t0 + timedelta(hours=3)),
            priority=1, sla_deadline=t0 + timedelta(hours=4))},
        vehicles={"V1": Vehicle(id="V1", capacity_kg=500, pos=loc_d,
                                current_load_kg=0, status=VehicleStatus.AT_DEPOT,
                                veh_type="truck", wade_capability=0.3)},
        road_graph=RoadGraph(
            nodes={"DEPOT": RoadNode("DEPOT", loc_d), "C1": RoadNode("C1", loc_c)},
            edges={("DEPOT", "C1"): RoadEdge("DEPOT", "C1", 2.0, 10.0,
                                             status=EdgeStatus.FLOODED, flood_level=0.4)},
            adjacency={"DEPOT": ["C1"]}),
    )
    state.events.append(Event(id="E1", event_type=EventType.TRAFFIC,
                              target="DEPOT->C1", severity=EventSeverity.HIGH,
                              started_at=t0, metrics={"factor": 4.0}))
    state.decisions.append(Decision(
        id="D1", timestamp=t0, event_id="E1", action=DecisionAction.REROUTE,
        engine=DecisionEngine.RULE_BASED, description="reroute around flood",
        impact_estimate={"delay_minutes_saved": 20.0}))
    return state


def test_round_trip_preserves_state():
    state = _small_state()
    snapshot = state.to_dict()
    restored = WorldState.from_dict(snapshot)
    assert restored.to_dict() == snapshot


def test_round_trip_restores_typed_values():
    restored = WorldState.from_dict(_small_state().to_dict())
    assert restored.clock == datetime(2026, 6, 4, 6, 0)
    assert restored.customers["C1"].priority == 1
    edge = restored.road_graph.edges[("DEPOT", "C1")]
    assert edge.status == EdgeStatus.FLOODED
    assert edge.is_passable(0.5) is True
    assert edge.is_passable(0.2) is False
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_serialization.py -v`
Expected: PASS (2 passed). (`to_dict`/`from_dict` were implemented in Task 2.)

- [ ] **Step 3: Commit**

```powershell
git add tests/test_serialization.py
git commit -m "test(contracts): round-trip JSON serialization for WorldState" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Routing DTOs

**Files:**
- Create: `fleet/contracts/dto.py`
- Test: `tests/test_dto.py`

- [ ] **Step 1: Write the failing test**

`tests/test_dto.py`:
```python
from datetime import datetime

from fleet.contracts.dto import (
    FleetVehicleSpec, TaskSpec, RoutingProblem, SolvedStop, RoutingSolution,
)


def test_build_routing_problem():
    t0 = datetime(2026, 6, 4, 6, 0)
    prob = RoutingProblem(
        locations=["DEPOT", "C1"],
        depot_id="DEPOT",
        time_matrix={"truck": [[0.0, 10.0], [10.0, 0.0]]},
        fleet=[FleetVehicleSpec(id="V1", capacity_kg=500, veh_type="truck",
                                shift_start=t0, shift_end=t0)],
        tasks=[TaskSpec(customer_id="C1", demand_kg=20.0, tw_start=t0, tw_end=t0,
                        service_time_min=10.0, priority=1)],
    )
    assert prob.time_matrix["truck"][0][1] == 10.0
    assert prob.fleet[0].capacity_kg == 500


def test_routing_solution_defaults():
    sol = RoutingSolution(
        routes={"V1": [SolvedStop(customer_id="C1", arrival=datetime(2026, 6, 4, 7),
                                  departure=datetime(2026, 6, 4, 7, 10),
                                  load_after=480.0)]},
        dropped=[])
    assert sol.feasible is True
    assert sol.metrics == {}
    assert sol.routes["V1"][0].load_after == 480.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.contracts.dto'`

- [ ] **Step 3: Write `fleet/contracts/dto.py`**

```python
"""Intermediate routing DTOs shared by CpuSolver and CuOptAdapter (spec §5.1).

Decouples the optimizer interface from WorldState so any solver maps to the
same problem/solution shape."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class FleetVehicleSpec:
    id: str
    capacity_kg: float
    veh_type: str               # selects which time_matrix to use
    shift_start: datetime
    shift_end: datetime
    # route always starts and ends at the depot (implicit, spec §6.9)


@dataclass
class TaskSpec:
    customer_id: str
    demand_kg: float
    tw_start: datetime
    tw_end: datetime
    service_time_min: float
    priority: int               # 1 = most urgent .. 4 = least urgent


@dataclass
class RoutingProblem:
    locations: List[str]                       # node ids: depot + customers
    depot_id: str
    time_matrix: Dict[str, List[List[float]]]  # veh_type -> NxN minutes (spec §6.5)
    fleet: List[FleetVehicleSpec]
    tasks: List[TaskSpec]


@dataclass
class SolvedStop:
    customer_id: str
    arrival: datetime
    departure: datetime
    load_after: float


@dataclass
class RoutingSolution:
    routes: Dict[str, List[SolvedStop]]        # vehicle_id -> ordered stops
    dropped: List[str]                          # customer_ids not scheduled -> DEFER
    feasible: bool = True
    metrics: Dict[str, float] = field(default_factory=dict)
    # metrics keys: total_distance_km, total_time_min
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dto.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/contracts/dto.py tests/test_dto.py
git commit -m "feat(contracts): routing DTOs (RoutingProblem/RoutingSolution)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Interface protocols

**Files:**
- Create: `fleet/contracts/interfaces.py`
- Test: `tests/test_interfaces.py`

- [ ] **Step 1: Write the failing test**

`tests/test_interfaces.py`:
```python
from fleet.contracts.interfaces import (
    Simulator, Detector, RouteOptimizer, Forecaster, DecisionEngine, Dispatcher,
)


class _OkSim:
    def tick(self, state): ...
    def inject_event(self, state, event_type, target, severity): ...


class _BadSim:
    def tick(self, state): ...
    # missing inject_event


def test_protocols_are_runtime_checkable():
    assert isinstance(_OkSim(), Simulator)
    assert not isinstance(_BadSim(), Simulator)


def test_all_six_interfaces_runtime_checkable():
    class Dummy:  # implements none of the protocol methods
        pass
    for proto in (Simulator, Detector, RouteOptimizer,
                  Forecaster, DecisionEngine, Dispatcher):
        # runtime_checkable protocols allow isinstance() without raising TypeError
        assert isinstance(Dummy(), proto) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_interfaces.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.contracts.interfaces'`

- [ ] **Step 3: Write `fleet/contracts/interfaces.py`**

```python
"""The six stable interfaces every module hides behind (spec §4).

Tests target these Protocols, not concrete impls, so swapping
CpuSolver<->CuOptAdapter or RuleBasedEngine<->ClaudeAgent never breaks tests."""

from typing import List, Protocol, runtime_checkable

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, Decision,
)
from fleet.contracts.dto import RoutingProblem, RoutingSolution


@runtime_checkable
class Simulator(Protocol):
    def tick(self, state: WorldState) -> None: ...
    def inject_event(self, state: WorldState, event_type: EventType,
                     target: str, severity: EventSeverity) -> Event: ...


@runtime_checkable
class Detector(Protocol):
    def detect(self, state: WorldState) -> List[Event]: ...


@runtime_checkable
class RouteOptimizer(Protocol):
    def solve(self, problem: RoutingProblem) -> RoutingSolution: ...


@runtime_checkable
class Forecaster(Protocol):
    def forecast(self, history: list, horizon_h: int) -> dict: ...


@runtime_checkable
class DecisionEngine(Protocol):
    def decide(self, state: WorldState, events: List[Event]) -> List[Decision]: ...


@runtime_checkable
class Dispatcher(Protocol):
    def apply(self, state: WorldState, decision: Decision) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_interfaces.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/contracts/interfaces.py tests/test_interfaces.py
git commit -m "feat(contracts): six runtime-checkable Protocol interfaces" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Config & settings

**Files:**
- Create: `config/settings.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import os

from config.settings import Settings, load_settings


def test_defaults():
    s = load_settings(env={})
    assert s.routing_engine == "cpu"
    assert s.decision_engine == "rule"
    assert s.forecaster_engine == "ewma"
    assert s.detector_engine == "rule"
    assert s.seed == 42
    assert s.tick_minutes == 5
    assert s.auto_approve_delay_threshold_min == 15.0
    assert s.sla_critical_threshold_min == 30.0


def test_env_overrides():
    s = load_settings(env={"ROUTING_ENGINE": "cuopt",
                           "DECISION_ENGINE": "claude",
                           "SEED": "7",
                           "TICK_MINUTES": "10"})
    assert s.routing_engine == "cuopt"
    assert s.decision_engine == "claude"
    assert s.seed == 7
    assert s.tick_minutes == 10


def test_is_frozen():
    s = Settings()
    try:
        s.seed = 1  # type: ignore[misc]
        raise AssertionError("Settings should be immutable")
    except Exception:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config.settings'`

- [ ] **Step 3: Write `config/settings.py`**

```python
"""Central configuration. Engine choices select which interface impl the
factory returns, so changing CPU<->cuOpt or rule<->claude is config-only."""

import os
from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True)
class Settings:
    routing_engine: str = "cpu"        # cpu | cuopt
    decision_engine: str = "rule"      # rule | claude
    detector_engine: str = "rule"      # rule | zscore
    forecaster_engine: str = "ewma"    # ewma | prophet
    seed: int = 42
    tick_minutes: int = 5
    anthropic_api_key: str = ""
    cuopt_endpoint: str = ""
    auto_approve_delay_threshold_min: float = 15.0   # spec §6.6
    sla_critical_threshold_min: float = 30.0         # spec §6.2


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Build Settings from environment variables (defaults to os.environ)."""
    e = os.environ if env is None else env
    return Settings(
        routing_engine=e.get("ROUTING_ENGINE", "cpu"),
        decision_engine=e.get("DECISION_ENGINE", "rule"),
        detector_engine=e.get("DETECTOR_ENGINE", "rule"),
        forecaster_engine=e.get("FORECASTER_ENGINE", "ewma"),
        seed=int(e.get("SEED", "42")),
        tick_minutes=int(e.get("TICK_MINUTES", "5")),
        anthropic_api_key=e.get("ANTHROPIC_API_KEY", ""),
        cuopt_endpoint=e.get("CUOPT_ENDPOINT", ""),
        auto_approve_delay_threshold_min=float(
            e.get("AUTO_APPROVE_DELAY_THRESHOLD_MIN", "15")),
        sla_critical_threshold_min=float(
            e.get("SLA_CRITICAL_THRESHOLD_MIN", "30")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```powershell
git add config/settings.py tests/test_config.py
git commit -m "feat(config): Settings + env loader (engine switches, thresholds)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Sample-world builder (`scenarios.py`)

**Files:**
- Create: `fleet/scenarios.py`
- Test: `tests/test_scenarios.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scenarios.py`:
```python
from fleet.contracts.state import WorldState, VehicleStatus
from fleet.scenarios import build_sample_state


def test_sample_shape():
    s = build_sample_state()
    assert isinstance(s, WorldState)
    assert len(s.vehicles) == 3
    assert len(s.customers) == 4
    assert s.depot.inventory  # non-empty


def test_sample_starts_at_depot():
    s = build_sample_state()
    assert all(v.status == VehicleStatus.AT_DEPOT for v in s.vehicles.values())
    assert all(v.current_load_kg == 0 for v in s.vehicles.values())


def test_sample_priorities_in_1_to_4():
    s = build_sample_state()
    assert all(1 <= c.priority <= 4 for c in s.customers.values())


def test_sample_graph_nodes_match_entities():
    s = build_sample_state()
    assert "DEPOT" in s.road_graph.nodes
    for cid in s.customers:
        assert cid in s.road_graph.nodes


def test_sample_round_trips():
    s = build_sample_state()
    assert WorldState.from_dict(s.to_dict()).to_dict() == s.to_dict()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scenarios.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.scenarios'`

- [ ] **Step 3: Write `fleet/scenarios.py`**

```python
"""Deterministic sample worlds for tests, the headless loop, and demos.
Migrated from MOPHONG_Hackathon simple_simulator.create_sample_state with
spec schema applied (priority 1-4, veh_type/wade_capability, flood_level)."""

from datetime import datetime, timedelta

from fleet.contracts.state import (
    WorldState, Depot, Location, Vehicle, VehicleStatus, CustomerProfile,
    TimeWindow, RoadGraph, RoadNode, RoadEdge,
)


def build_sample_state(base_time: datetime = datetime(2026, 6, 4, 6, 0)) -> WorldState:
    """1 depot, 3 vehicles, 4 customers in HCM District 1."""
    depot_loc = Location(10.8231, 106.6297, "1 Nguyen Hue, Q.1, HCM", "Kho Chinh HCM")
    depot = Depot(
        location=depot_loc,
        inventory={"SKU001": 100, "SKU002": 50, "SKU003": 80},
        opening_time=base_time,
        closing_time=base_time + timedelta(hours=12),
    )

    vehicles = {}
    for i in range(1, 4):
        vid = f"V{i:03d}"
        vehicles[vid] = Vehicle(
            id=vid, capacity_kg=500, pos=depot_loc, current_load_kg=0,
            status=VehicleStatus.AT_DEPOT,
            shift_start=base_time, shift_end=base_time + timedelta(hours=10),
            veh_type="truck", wade_capability=0.3,
        )

    cust_specs = [
        ("C001", "supermarket", 10.8050, 106.6300, "BigC Q.1",
         {"SKU001": 10, "SKU002": 5}, 1, 1, 3, 4),
        ("C002", "market", 10.7748, 106.6987, "Cho Ben Thanh",
         {"SKU001": 20}, 2, 1.5, 3.5, 5),
        ("C003", "convenience_store", 10.8150, 106.6150, "MiniMart Le Loi",
         {"SKU002": 15, "SKU003": 8}, 3, 2, 4, 6),
        ("C004", "restaurant", 10.8300, 106.6400, "Nha hang A Chau",
         {"SKU003": 30}, 2, 1.75, 4, 5.5),
    ]
    customers = {}
    for cid, ctype, lat, lng, name, orders, prio, tw_s, tw_e, sla_h in cust_specs:
        customers[cid] = CustomerProfile(
            id=cid, type=ctype,
            location=Location(lat, lng, name, name),
            orders=orders,
            time_window=TimeWindow(base_time + timedelta(hours=tw_s),
                                   base_time + timedelta(hours=tw_e)),
            priority=prio,
            sla_deadline=base_time + timedelta(hours=sla_h),
        )

    nodes = {"DEPOT": RoadNode("DEPOT", depot_loc)}
    for cid in customers:
        nodes[cid] = RoadNode(cid, customers[cid].location)

    # depot <-> every customer (both directions) so every stop is reachable.
    edge_list = [
        ("DEPOT", "C001", 2.0, 10.0), ("DEPOT", "C002", 4.0, 15.0),
        ("DEPOT", "C003", 2.5, 12.0), ("DEPOT", "C004", 3.0, 14.0),
        ("C001", "C002", 3.0, 12.0), ("C002", "C003", 2.5, 10.0),
        ("C003", "C004", 2.0, 8.0), ("C004", "DEPOT", 3.5, 15.0),
    ]
    edges = {}
    adjacency = {n: [] for n in nodes}
    for a, b, km, mins in edge_list:
        edges[(a, b)] = RoadEdge(a, b, km, mins)
        edges[(b, a)] = RoadEdge(b, a, km, mins)
        adjacency[a].append(b)
        adjacency[b].append(a)

    return WorldState(
        clock=base_time,
        depot=depot,
        customers=customers,
        vehicles=vehicles,
        road_graph=RoadGraph(nodes=nodes, edges=edges, adjacency=adjacency),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scenarios.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/scenarios.py tests/test_scenarios.py
git commit -m "feat(scenarios): deterministic sample world (1 depot, 3 veh, 4 cust)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Close out M0 — full suite green, remove `MOPHONG_Hackathon/`

**Files:**
- Delete: `MOPHONG_Hackathon/` (git-untracked reference; migration complete)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–7 pass; ~20 passed, 0 failed)

- [ ] **Step 2: Delete the reference directory**

Run (PowerShell):
```powershell
Remove-Item -Recurse -Force MOPHONG_Hackathon
```
Expected: directory gone (`Test-Path MOPHONG_Hackathon` → `False`).

- [ ] **Step 3: Verify nothing imported it**

Run: `pytest -q`
Expected: PASS (no import errors — `fleet/` does not depend on `MOPHONG_Hackathon/`).

- [ ] **Step 4: Commit**

```powershell
git add -A
git commit -m "chore: remove MOPHONG_Hackathon reference (schema migrated to fleet/contracts)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

# Milestone M1 — Walking skeleton (stubs + headless loop)

> Every interface gets a minimal default impl now and a real impl in a later
> milestone. The loop exercises tick → detect → decide → approve → dispatch →
> audit end-to-end. Optimizer/Forecaster are wired but not yet called by the
> rule engine (they activate in M3/M5/M6).

### Task 9: `WorldSimulator` stub

**Files:**
- Create: `fleet/simulator/engine.py`
- Test: `tests/test_simulator.py`

- [ ] **Step 1: Write the failing test**

`tests/test_simulator.py`:
```python
from datetime import timedelta

from fleet.contracts.interfaces import Simulator
from fleet.contracts.state import EventType, EventSeverity
from fleet.simulator.engine import WorldSimulator
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def test_conforms_to_protocol():
    assert isinstance(WorldSimulator(load_settings()), Simulator)


def test_tick_advances_clock_and_counter():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"TICK_MINUTES": "5"}))
    start = s.clock
    sim.tick(s)
    assert s.sim_tick == 1
    assert s.clock == start + timedelta(minutes=5)


def test_inject_event_appends_active_event():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    evt = sim.inject_event(s, EventType.TRAFFIC, "DEPOT->C001", EventSeverity.HIGH)
    assert evt.ended_at is None
    assert evt in s.get_active_events()
    assert evt.id.startswith("EVT_")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_simulator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.simulator.engine'`

- [ ] **Step 3: Write `fleet/simulator/engine.py`**

```python
"""Default world simulator. STUB for M1 (clock + event injection only).
M2 adds demand generation, vehicle movement along the matrix, inventory
consumption, and scheduled restock."""

from datetime import timedelta

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity,
)


class WorldSimulator:
    def __init__(self, settings):
        self.settings = settings
        self._evt_seq = 0

    def tick(self, state: WorldState) -> None:
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1

    def inject_event(self, state: WorldState, event_type: EventType,
                     target: str, severity: EventSeverity) -> Event:
        self._evt_seq += 1
        evt = Event(
            id=f"EVT_{self._evt_seq:03d}", event_type=event_type,
            target=target, severity=severity, started_at=state.clock,
            description=f"injected {event_type.value} on {target}",
        )
        state.events.append(evt)
        return evt
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_simulator.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/simulator/engine.py tests/test_simulator.py
git commit -m "feat(simulator): WorldSimulator stub (clock + inject_event)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: `RuleDetector` stub

**Files:**
- Create: `fleet/detection/rules.py`
- Test: `tests/test_detector.py`

- [ ] **Step 1: Write the failing test**

`tests/test_detector.py`:
```python
from fleet.contracts.interfaces import Detector
from fleet.detection.rules import RuleDetector
from fleet.scenarios import build_sample_state


def test_conforms_to_protocol():
    assert isinstance(RuleDetector(), Detector)


def test_detect_returns_empty_list_for_now():
    # M6 adds threshold rules; M1 stub finds nothing on its own.
    assert RuleDetector().detect(build_sample_state()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.detection.rules'`

- [ ] **Step 3: Write `fleet/detection/rules.py`**

```python
"""Rule-based anomaly detector. STUB for M1 (returns nothing).
M6 adds threshold rules (e.g. traffic_factor >= 4 -> HIGH) and a ZScoreDetector."""

from typing import List

from fleet.contracts.state import WorldState, Event


class RuleDetector:
    def detect(self, state: WorldState) -> List[Event]:
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_detector.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/detection/rules.py tests/test_detector.py
git commit -m "feat(detection): RuleDetector stub" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: `CpuSolver` stub

**Files:**
- Create: `fleet/routing/cpu_solver.py`
- Test: `tests/test_cpu_solver.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cpu_solver.py`:
```python
from datetime import datetime

from fleet.contracts.interfaces import RouteOptimizer
from fleet.contracts.dto import (
    RoutingProblem, FleetVehicleSpec, TaskSpec, RoutingSolution,
)
from fleet.routing.cpu_solver import CpuSolver


def _problem():
    t0 = datetime(2026, 6, 4, 6, 0)
    return RoutingProblem(
        locations=["DEPOT", "C1"], depot_id="DEPOT",
        time_matrix={"truck": [[0.0, 10.0], [10.0, 0.0]]},
        fleet=[FleetVehicleSpec("V1", 500, "truck", t0, t0)],
        tasks=[TaskSpec("C1", 20.0, t0, t0, 10.0, 1)],
    )


def test_conforms_to_protocol():
    assert isinstance(CpuSolver(), RouteOptimizer)


def test_returns_routing_solution():
    sol = CpuSolver().solve(_problem())
    assert isinstance(sol, RoutingSolution)
    # M1 stub schedules nothing yet; real greedy VRPTW lands in M3.
    assert sol.dropped == ["C1"]
    assert sol.feasible is False
    assert "V1" in sol.routes and sol.routes["V1"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cpu_solver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.routing.cpu_solver'`

- [ ] **Step 3: Write `fleet/routing/cpu_solver.py`**

```python
"""CPU route optimizer. STUB for M1 (empty routes, everything dropped).
M3 implements greedy-insertion VRPTW honoring capacity + time windows, using
fleet/routing/matrix.py (Dijkstra) to build the per-veh_type time matrix."""

from fleet.contracts.dto import RoutingProblem, RoutingSolution


class CpuSolver:
    def solve(self, problem: RoutingProblem) -> RoutingSolution:
        return RoutingSolution(
            routes={v.id: [] for v in problem.fleet},
            dropped=[t.customer_id for t in problem.tasks],
            feasible=False,
            metrics={"total_distance_km": 0.0, "total_time_min": 0.0},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cpu_solver.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/routing/cpu_solver.py tests/test_cpu_solver.py
git commit -m "feat(routing): CpuSolver stub (RouteOptimizer default)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: `EwmaForecaster` stub

**Files:**
- Create: `fleet/forecast/ewma.py`
- Test: `tests/test_forecaster.py`

- [ ] **Step 1: Write the failing test**

`tests/test_forecaster.py`:
```python
from fleet.contracts.interfaces import Forecaster
from fleet.forecast.ewma import EwmaForecaster


def test_conforms_to_protocol():
    assert isinstance(EwmaForecaster(), Forecaster)


def test_forecast_returns_dict():
    out = EwmaForecaster().forecast(history=[], horizon_h=4)
    assert isinstance(out, dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_forecaster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.forecast.ewma'`

- [ ] **Step 3: Write `fleet/forecast/ewma.py`**

```python
"""EWMA demand forecaster. STUB for M1 (returns empty forecast).
M6 implements exponential smoothing + hourly seasonality; Prophet plugs in later."""

from typing import Dict


class EwmaForecaster:
    def forecast(self, history: list, horizon_h: int) -> Dict[str, float]:
        return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_forecaster.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/forecast/ewma.py tests/test_forecaster.py
git commit -m "feat(forecast): EwmaForecaster stub" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: `RuleBasedEngine` (default decision engine)

**Files:**
- Create: `fleet/agent/rule_based.py`
- Test: `tests/test_rule_engine.py`

- [ ] **Step 1: Write the failing test**

`tests/test_rule_engine.py`:
```python
from datetime import datetime

from fleet.contracts.interfaces import DecisionEngine
from fleet.contracts.state import (
    Event, EventType, EventSeverity, DecisionAction, DecisionEngine as Eng,
)
from fleet.agent.rule_based import RuleBasedEngine
from fleet.scenarios import build_sample_state


def _evt(et, sev="low"):
    return Event(id="E1", event_type=et, target="DEPOT->C001",
                 severity=EventSeverity(sev), started_at=datetime(2026, 6, 4, 7))


def test_conforms_to_protocol():
    assert isinstance(RuleBasedEngine(), DecisionEngine)


def test_no_events_no_decisions():
    assert RuleBasedEngine().decide(build_sample_state(), []) == []


def test_traffic_maps_to_reroute():
    decs = RuleBasedEngine().decide(build_sample_state(), [_evt(EventType.TRAFFIC)])
    assert len(decs) == 1
    assert decs[0].action == DecisionAction.REROUTE
    assert decs[0].engine == Eng.RULE_BASED
    assert decs[0].event_id == "E1"


def test_breakdown_maps_to_reallocate():
    decs = RuleBasedEngine().decide(build_sample_state(),
                                    [_evt(EventType.VEHICLE_BREAKDOWN)])
    assert decs[0].action == DecisionAction.REALLOCATE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rule_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.agent.rule_based'`

- [ ] **Step 3: Write `fleet/agent/rule_based.py`**

```python
"""Rule-based decision engine (default). Emits one decision per event using a
fixed event->action map. M5 adds ClaudeAgent (ReAct + tool-calling) behind the
same DecisionEngine interface; this stays as the no-API-key fallback."""

from typing import List

from fleet.contracts.state import (
    WorldState, Event, EventType, Decision, DecisionAction, DecisionEngine,
)

_ACTION_BY_EVENT = {
    EventType.TRAFFIC: DecisionAction.REROUTE,
    EventType.FLOODED_AREA: DecisionAction.REROUTE,
    EventType.DEMAND_SURGE: DecisionAction.REPRIORITIZE,
    EventType.URGENT_ORDER: DecisionAction.REPRIORITIZE,
    EventType.INVENTORY_SHORTAGE: DecisionAction.DEFER,
    EventType.VEHICLE_BREAKDOWN: DecisionAction.REALLOCATE,
}


class RuleBasedEngine:
    def __init__(self):
        self._seq = 0

    def decide(self, state: WorldState, events: List[Event]) -> List[Decision]:
        out: List[Decision] = []
        for e in events:
            self._seq += 1
            action = _ACTION_BY_EVENT.get(e.event_type, DecisionAction.REROUTE)
            out.append(Decision(
                id=f"DEC_{self._seq:03d}", timestamp=state.clock, event_id=e.id,
                action=action, engine=DecisionEngine.RULE_BASED,
                description=f"[rule] respond to {e.event_type.value} on {e.target}",
                impact_estimate={"added_delay_min": 5.0},
                reasoning="rule-based event->action mapping (M1 stub)",
            ))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rule_engine.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/agent/rule_based.py tests/test_rule_engine.py
git commit -m "feat(agent): RuleBasedEngine default decision engine" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 14: Approval policy

**Files:**
- Create: `fleet/dispatch/approval.py`
- Test: `tests/test_approval.py`

- [ ] **Step 1: Write the failing test**

`tests/test_approval.py`:
```python
from datetime import datetime

from fleet.contracts.state import (
    Decision, DecisionAction, DecisionEngine, EventSeverity,
)
from fleet.dispatch.approval import should_auto_approve
from config.settings import load_settings

S = load_settings()


def _dec(action, added_delay=5.0):
    return Decision(id="D", timestamp=datetime(2026, 6, 4, 7), event_id="E",
                    action=action, engine=DecisionEngine.RULE_BASED, description="",
                    impact_estimate={"added_delay_min": added_delay})


def test_small_reroute_auto_approved():
    assert should_auto_approve(_dec(DecisionAction.REROUTE, 5.0),
                               EventSeverity.LOW, S) is True


def test_large_reroute_needs_approval():
    assert should_auto_approve(_dec(DecisionAction.REROUTE, 25.0),
                               EventSeverity.LOW, S) is False


def test_defer_and_cancel_and_reallocate_need_approval():
    for a in (DecisionAction.DEFER, DecisionAction.CANCEL, DecisionAction.REALLOCATE):
        assert should_auto_approve(_dec(a), EventSeverity.LOW, S) is False


def test_critical_severity_always_needs_approval():
    assert should_auto_approve(_dec(DecisionAction.REROUTE, 5.0),
                               EventSeverity.CRITICAL, S) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_approval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.dispatch.approval'`

- [ ] **Step 3: Write `fleet/dispatch/approval.py`**

```python
"""Approval gate policy (spec §6.6). Auto-execute only small REROUTE/RESCHEDULE;
escalate DEFER/CANCEL/REALLOCATE (and anything CRITICAL) to a human queue."""

from typing import Optional

from fleet.contracts.state import Decision, DecisionAction, EventSeverity

_NEEDS_APPROVAL_ACTIONS = {
    DecisionAction.DEFER,
    DecisionAction.CANCEL,
    DecisionAction.REALLOCATE,
}
_AUTO_CANDIDATE_ACTIONS = {
    DecisionAction.REROUTE,
    DecisionAction.RESCHEDULE,
}


def should_auto_approve(decision: Decision,
                        severity: Optional[EventSeverity],
                        settings) -> bool:
    if severity == EventSeverity.CRITICAL:
        return False
    if decision.action in _NEEDS_APPROVAL_ACTIONS:
        return False
    if decision.action in _AUTO_CANDIDATE_ACTIONS:
        added = decision.impact_estimate.get("added_delay_min", 0.0)
        return added <= settings.auto_approve_delay_threshold_min
    return False  # REPRIORITIZE / ACCELERATE etc. default to manual
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_approval.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/dispatch/approval.py tests/test_approval.py
git commit -m "feat(dispatch): approval policy (auto vs needs-approval)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 15: `Dispatcher`

**Files:**
- Create: `fleet/dispatch/dispatcher.py`
- Test: `tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

`tests/test_dispatcher.py`:
```python
from datetime import datetime

from fleet.contracts.interfaces import Dispatcher as DispatcherProto
from fleet.contracts.state import Decision, DecisionAction, DecisionEngine
from fleet.dispatch.dispatcher import Dispatcher
from fleet.scenarios import build_sample_state


def test_conforms_to_protocol():
    assert isinstance(Dispatcher(), DispatcherProto)


def test_apply_marks_executed():
    s = build_sample_state()
    d = Decision(id="D1", timestamp=s.clock, event_id="E1",
                 action=DecisionAction.REROUTE, engine=DecisionEngine.RULE_BASED,
                 description="x")
    Dispatcher().apply(s, d)
    assert d.executed_at == s.clock
    assert d.execution_result == {"status": "applied"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dispatcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.dispatch.dispatcher'`

- [ ] **Step 3: Write `fleet/dispatch/dispatcher.py`**

```python
"""Applies an approved decision to the WorldState and records execution.
M1: records execution metadata only. M3+ mutates plan/vehicles for real
(e.g. REROUTE swaps in a re-solved route)."""

from fleet.contracts.state import WorldState, Decision


class Dispatcher:
    def apply(self, state: WorldState, decision: Decision) -> None:
        decision.executed_at = state.clock
        decision.execution_result = {"status": "applied"}
        # M3+: mutate state.plan / vehicles based on decision.action
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dispatcher.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/dispatch/dispatcher.py tests/test_dispatcher.py
git commit -m "feat(dispatch): Dispatcher records decision execution" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 16: Component factory

**Files:**
- Create: `fleet/factory.py`
- Test: `tests/test_factory.py`

- [ ] **Step 1: Write the failing test**

`tests/test_factory.py`:
```python
from fleet.contracts.interfaces import (
    Simulator, Detector, RouteOptimizer, Forecaster, DecisionEngine, Dispatcher,
)
from fleet.factory import Components, build_components
from fleet.routing.cpu_solver import CpuSolver
from fleet.agent.rule_based import RuleBasedEngine
from config.settings import load_settings


def test_build_components_returns_conforming_impls():
    c = build_components(load_settings())
    assert isinstance(c, Components)
    assert isinstance(c.simulator, Simulator)
    assert isinstance(c.detector, Detector)
    assert isinstance(c.optimizer, RouteOptimizer)
    assert isinstance(c.forecaster, Forecaster)
    assert isinstance(c.decision_engine, DecisionEngine)
    assert isinstance(c.dispatcher, Dispatcher)


def test_cpu_and_rule_are_the_defaults():
    c = build_components(load_settings(env={}))
    assert isinstance(c.optimizer, CpuSolver)
    assert isinstance(c.decision_engine, RuleBasedEngine)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.factory'`

- [ ] **Step 3: Write `fleet/factory.py`**

```python
"""Composition root: reads Settings and returns concrete impls behind the
interfaces. This is the ONLY place that knows about every impl, so swapping an
engine is a config change here, not in callers (loop, agent, ui)."""

from dataclasses import dataclass

from fleet.contracts.interfaces import (
    Simulator, Detector, RouteOptimizer, Forecaster, DecisionEngine, Dispatcher,
)
from fleet.simulator.engine import WorldSimulator
from fleet.detection.rules import RuleDetector
from fleet.routing.cpu_solver import CpuSolver
from fleet.forecast.ewma import EwmaForecaster
from fleet.agent.rule_based import RuleBasedEngine
from fleet.dispatch.dispatcher import Dispatcher as DispatcherImpl


@dataclass
class Components:
    simulator: Simulator
    detector: Detector
    optimizer: RouteOptimizer
    forecaster: Forecaster
    decision_engine: DecisionEngine
    dispatcher: Dispatcher


def build_components(settings) -> Components:
    # Routing engine (cuOpt adapter arrives in M4; falls back to CPU until then).
    if settings.routing_engine == "cuopt":
        optimizer: RouteOptimizer = CpuSolver()  # TODO M4: CuOptAdapter(settings)
    else:
        optimizer = CpuSolver()

    # Decision engine (Claude arrives in M5; rule-based is the default/fallback).
    if settings.decision_engine == "claude":
        decision_engine: DecisionEngine = RuleBasedEngine()  # TODO M5: ClaudeAgent
    else:
        decision_engine = RuleBasedEngine()

    return Components(
        simulator=WorldSimulator(settings),
        detector=RuleDetector(),
        optimizer=optimizer,
        forecaster=EwmaForecaster(),
        decision_engine=decision_engine,
        dispatcher=DispatcherImpl(),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_factory.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/factory.py tests/test_factory.py
git commit -m "feat(factory): build_components composition root" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 17: The loop

**Files:**
- Create: `fleet/loop.py`
- Test: `tests/test_loop.py`

- [ ] **Step 1: Write the failing test**

`tests/test_loop.py`:
```python
from datetime import timedelta

from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.loop import run_loop
from fleet.contracts.state import EventType, EventSeverity, DecisionAction, ApprovalStatus
from config.settings import load_settings


def _silent(*_args, **_kw):
    pass


def test_loop_advances_clock():
    s = build_sample_state()
    settings = load_settings(env={"TICK_MINUTES": "5"})
    comps = build_components(settings)
    start = s.clock
    run_loop(s, comps, n_ticks=3, settings=settings, logger=_silent)
    assert s.sim_tick == 3
    assert s.clock == start + timedelta(minutes=15)


def test_low_severity_event_flows_to_dispatched_decision():
    s = build_sample_state()
    settings = load_settings()
    comps = build_components(settings)
    comps.simulator.inject_event(s, EventType.TRAFFIC, "DEPOT->C001",
                                 EventSeverity.LOW)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    assert len(s.decisions) == 1
    d = s.decisions[-1]
    assert d.action == DecisionAction.REROUTE
    assert d.approval_status == ApprovalStatus.APPROVED
    assert d.approved_by == "auto"
    assert d.executed_at is not None


def test_critical_event_is_queued_not_executed():
    s = build_sample_state()
    settings = load_settings()
    comps = build_components(settings)
    comps.simulator.inject_event(s, EventType.VEHICLE_BREAKDOWN, "V001",
                                 EventSeverity.CRITICAL)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    d = s.decisions[-1]
    assert d.approval_status == ApprovalStatus.PENDING
    assert d.executed_at is None
    assert d in s.get_pending_decisions()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_loop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.loop'`

- [ ] **Step 3: Write `fleet/loop.py`**

```python
"""Headless orchestration loop (spec §7).

Each tick: simulator.tick -> detector.detect (+ active injected events) ->
decision_engine.decide -> approval gate -> dispatcher.apply -> audit log.
The same `state` + components are reused by the Streamlit UI in M7."""

from typing import Callable

from fleet.contracts.state import WorldState, ApprovalStatus
from fleet.factory import Components
from fleet.dispatch.approval import should_auto_approve


def run_loop(state: WorldState, components: Components, n_ticks: int,
             settings, logger: Callable[..., None] = print) -> WorldState:
    for _ in range(n_ticks):
        components.simulator.tick(state)

        detected = components.detector.detect(state)
        active = list(state.get_active_events())
        events, seen = [], set()
        for e in detected + active:               # detector output + injected
            if e.id not in seen:
                seen.add(e.id)
                events.append(e)

        severity_by_event = {e.id: e.severity for e in events}
        decisions = components.decision_engine.decide(state, events)

        for d in decisions:
            state.decisions.append(d)
            severity = severity_by_event.get(d.event_id)
            if should_auto_approve(d, severity, settings):
                d.approval_status = ApprovalStatus.APPROVED
                d.approved_by = "auto"
                d.approved_at = state.clock
                components.dispatcher.apply(state, d)
                verdict = "AUTO-APPLIED"
            else:
                verdict = "QUEUED(approval)"
            logger(f"t={state.sim_tick} clock={state.clock} "
                   f"{d.action.value} <- {d.event_id} [{verdict}]")

        logger(f"t={state.sim_tick} clock={state.clock} "
               f"active_events={len(events)} pending={len(state.get_pending_decisions())}")
    return state


def main() -> None:
    from fleet.scenarios import build_sample_state
    from fleet.factory import build_components
    from config.settings import load_settings
    from fleet.contracts.state import EventType, EventSeverity

    settings = load_settings()
    state = build_sample_state()
    components = build_components(settings)
    # demo: inject one traffic event so the decision path is visible
    components.simulator.inject_event(state, EventType.TRAFFIC, "DEPOT->C001",
                                      EventSeverity.LOW)
    run_loop(state, components, n_ticks=10, settings=settings)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_loop.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```powershell
git add fleet/loop.py tests/test_loop.py
git commit -m "feat(loop): headless orchestration loop (tick->decide->approve->dispatch)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 18: Close out M1 — smoke-run the skeleton + README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1–17 pass; 0 failed)

- [ ] **Step 2: Smoke-run the headless loop**

Run (PowerShell, venv active):
```powershell
python -m fleet.loop
```
Expected: 10 ticks of log lines printed, clock advanced 50 minutes (10 × 5 min); the active injected TRAFFIC event produces a `REROUTE ... [AUTO-APPLIED]` line each tick (the M1 rule engine does not yet dedupe handled events — that lands in M5); no traceback.

- [ ] **Step 3: Write `README.md`**

```markdown
# Fleet Optimizer — AI Agent for Realtime Delivery Fleet Optimization

Hub-and-spoke (1 depot) VRPTW fleet optimizer. Base project: a stable
contract/interface layer + a headless walking-skeleton loop. Each module
improves independently behind its interface (see the milestone plans).

## Layout
- `fleet/contracts/` — WorldState entities, 6 Protocol interfaces, routing DTOs (depends on nothing)
- `fleet/simulator/` — the world (tick, events; demand/movement in M2)
- `fleet/detection/` — anomaly detection (rules now; z-score in M6)
- `fleet/routing/` — `CpuSolver` (greedy VRPTW in M3) + `CuOptAdapter` (M4) + `matrix.py` (Dijkstra, M3)
- `fleet/forecast/` — `EwmaForecaster` (M6) + Prophet (later)
- `fleet/agent/` — `RuleBasedEngine` (default) + `ClaudeAgent` (M5)
- `fleet/dispatch/` — approval policy + dispatcher
- `fleet/loop.py` — headless orchestration loop
- `config/settings.py` — engine switches (CPU/cuOpt, rule/claude) + thresholds

## Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run
```powershell
pytest -v             # full test suite
python -m fleet.loop  # headless skeleton demo
```

## Configure (env vars)
`ROUTING_ENGINE=cpu|cuopt`, `DECISION_ENGINE=rule|claude`, `SEED`, `TICK_MINUTES`,
`ANTHROPIC_API_KEY`, `CUOPT_ENDPOINT`. Defaults run with no GPU and no API key.
```

- [ ] **Step 4: Commit**

```powershell
git add README.md
git commit -m "docs: README for fleet base project; M1 walking skeleton complete" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Definition of done (this plan)

- `pytest -v` green across all tasks (contracts, serialization round-trip, scenarios, all six stubs, factory, loop).
- `python -m fleet.loop` runs headless end-to-end with no traceback; injected event flows through to an auto-applied (or queued) decision.
- Every interface has a default impl chosen by `config/settings.py` via `build_components`.
- `MOPHONG_Hackathon/` removed; schema fully migrated into `fleet/contracts/state.py`.
- Branch `feat/base-project` holds the work, ready for review/merge.

Next plan: **M2 — real Simulator** (demand seasonality + noise from `seed`, vehicle movement along the time matrix, inventory consumption + scheduled restock, `INVENTORY_SHORTAGE` events).
