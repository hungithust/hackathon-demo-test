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
        "task_data": {
            "task_locations": task_locations,
            "demand": [demand_row],
            "task_time_windows": tws,
            "service_times": service,
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
    res = response.get("response", {})
    if isinstance(res, dict):
        sr = res.get("solver_response", res)
    else:
        sr = {"status": -1}
    
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

        # endpoint formatted as "host:port" (e.g. "localhost:5000")
        host, _, port = endpoint.partition(":")
        
        host = host or "localhost"
        port = int(port or "5000")

        def transport(request: dict) -> dict:
            import requests
            import time

            request_url = f"http://{host}:{port}/cuopt/request"
            solution_url = f"http://{host}:{port}/cuopt/solution"

            if "solver_config" not in request:
                request["solver_config"] = {"time_limit": 2.0}

            try:
                # Nộp bài toán
                response = requests.post(request_url, json=request, timeout=10)
                response.raise_for_status()
                req_id = response.json().get("reqId")
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"Lỗi khi nộp bài toán lên cuOpt API: {e}")

            if not req_id:
                raise RuntimeError("API cuOpt không trả về reqId.")

            # Chờ kết quả (Polling)
            max_retries = 30
            for attempt in range(max_retries):
                try:
                    sol_response = requests.get(f"{solution_url}/{req_id}", timeout=10)
                    sol_response.raise_for_status()
                    sol_data = sol_response.json()

                    if "response" in sol_data:
                        import json
                        print("\n" + "="*50)
                        print("[CuOptAdapter] RAW API RESPONSE FROM LOCAL CUOPT:")
                        print(json.dumps(sol_data, indent=2))
                        print("="*50 + "\n")
                        return sol_data
                except requests.exceptions.RequestException as e:
                    raise RuntimeError(f"Lỗi khi lấy kết quả từ cuOpt API: {e}")

                time.sleep(2)

            raise RuntimeError("Hết thời gian chờ. Hệ thống cuOpt có thể đang quá tải.")

        return transport