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
