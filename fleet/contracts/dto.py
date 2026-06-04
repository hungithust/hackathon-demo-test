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
