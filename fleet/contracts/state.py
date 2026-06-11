"""World State — shared contract for all modules (simulator, detection, agent, ui).

Migrated from MOPHONG_Hackathon/ai-fleet-optimizer/world_state_implementation.py
with spec §6 schema reconciliations applied (see plan header).
This module imports NOTHING from other fleet modules.
"""

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum, IntEnum
from typing import Dict, List, Optional


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
    LOCAL_NIM = "local_nim"
    LOCAL_API = "local_api"


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
    service_time_min: float = 10.0
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
    demand_kg: float = 0.0          # kg to deliver at this stop (for live load %)


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
    id: str = ""                   # unique edge id; auto-derived from endpoints if empty
    congestion_start_frac: float = 0.0  # fraction along edge where jam begins [0..1]
    congestion_end_frac: float = 1.0    # fraction along edge where jam ends [0..1]

    def __post_init__(self):
        if not self.id:
            self.id = f"{self.from_node}->{self.to_node}"

    @property
    def effective_time(self) -> float:
        flood_penalty = 100.0 if self.flood_level > 0.0 else 1.0
        # Only the congested segment [congestion_start_frac, congestion_end_frac]
        # incurs the traffic_factor penalty; the rest is at normal speed.
        cong_frac = max(0.0, min(1.0, self.congestion_end_frac - self.congestion_start_frac))
        effective_traffic = (1.0 - cong_frac) + cong_frac * self.traffic_factor
        return self.base_time_minutes * effective_traffic * flood_penalty

    def is_passable(self, wade_capability: float) -> bool:
        """BLOCKED and FLOODED status edges are forbidden for all vehicles.
        An OPEN edge with partial flood depth is checked against wade_capability."""
        if self.status in (EdgeStatus.BLOCKED, EdgeStatus.FLOODED):
            return False
        return self.flood_level <= wade_capability


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
