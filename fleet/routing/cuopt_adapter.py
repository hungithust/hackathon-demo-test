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
