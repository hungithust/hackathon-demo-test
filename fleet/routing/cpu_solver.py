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

# OR-Tools first-solution constructors (pha 1: dựng nghiệm khởi đầu).
_FIRST_SOLUTION = {
    "path_cheapest_arc": "PATH_CHEAPEST_ARC",
    "parallel_cheapest_insertion": "PARALLEL_CHEAPEST_INSERTION",
    "savings": "SAVINGS",
    "christofides": "CHRISTOFIDES",
    "automatic": "AUTOMATIC",
}
# OR-Tools local-search metaheuristics (pha 2: cải thiện nghiệm — phần "tối ưu" VRP).
_METAHEURISTIC = {
    "greedy_descent": "GREEDY_DESCENT",
    "guided_local_search": "GUIDED_LOCAL_SEARCH",
    "simulated_annealing": "SIMULATED_ANNEALING",
    "tabu_search": "TABU_SEARCH",
}


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

        starts = [problem.locations.index(f.start_location or problem.depot_id) for f in problem.fleet]
        ends = [depot] * num_vehicles
        manager = pywrapcp.RoutingIndexManager(n, num_vehicles, starts, ends)
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

        solution = routing.SolveWithParameters(self._search_parameters())
        if solution is None:
            return RoutingSolution(
                routes={f.id: [] for f in problem.fleet},
                dropped=[t.customer_id for t in problem.tasks],
                feasible=False, metrics={"total_time_min": 0.0})

        return self._read(problem, manager, routing, solution, time_dim,
                          demand, service, base, depot)

    def _search_parameters(self):
        """Build OR-Tools search params from settings. Default (no metaheuristic,
        no limits) = PATH_CHEAPEST_ARC only — the deterministic greedy construction
        that the validated dataset was generated with. Setting solver_metaheuristic
        (or a positive solver_time_limit_sec, kept for back-compat) turns on the
        local-search optimization phase. Prefer solver_solution_limit for a
        machine-independent, reproducible stop; the wall-clock time limit consumes
        its full budget per solve even on tiny problems."""
        s = self.settings
        params = pywrapcp.DefaultRoutingSearchParameters()

        fs = str(getattr(s, "solver_first_solution", "") or "path_cheapest_arc").lower()
        params.first_solution_strategy = getattr(
            routing_enums_pb2.FirstSolutionStrategy,
            _FIRST_SOLUTION.get(fs, "PATH_CHEAPEST_ARC"))

        time_limit = int(getattr(s, "solver_time_limit_sec", 0) or 0)
        sol_limit = int(getattr(s, "solver_solution_limit", 0) or 0)
        meta = str(getattr(s, "solver_metaheuristic", "") or "").lower()
        if meta in ("", "none", "off") and time_limit > 0:
            meta = "guided_local_search"      # back-compat: a time limit implied GLS

        if meta not in ("", "none", "off"):
            params.local_search_metaheuristic = getattr(
                routing_enums_pb2.LocalSearchMetaheuristic,
                _METAHEURISTIC.get(meta, "GUIDED_LOCAL_SEARCH"))
            # A metaheuristic loops until it hits a stop. Honor whichever limits
            # are given; if none, cap solutions so tiny problems still terminate.
            if sol_limit > 0:
                params.solution_limit = sol_limit
            if time_limit > 0:
                params.time_limit.FromSeconds(time_limit)
            if sol_limit <= 0 and time_limit <= 0:
                params.solution_limit = 100
        return params

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
                if ix == routing.Start(vehicle_id):
                    continue
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
