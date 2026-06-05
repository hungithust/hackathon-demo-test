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
