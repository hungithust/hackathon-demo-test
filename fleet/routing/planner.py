"""Orchestrates planning: build the problem, solve it, and write the resulting
routes into state.plan. Returns the dropped customer ids (candidates for DEFER).

Keeps the loop/agent decoupled from the optimizer impl: they call plan_routes
with whichever RouteOptimizer the factory selected."""

from typing import List

from fleet.contracts.state import WorldState, VehicleRoute, Stop
from fleet.contracts.interfaces import RouteOptimizer
from fleet.routing.matrix import build_routing_problem


def plan_routes(state: WorldState, optimizer: RouteOptimizer,
                depot_id: str = "DEPOT") -> List[str]:
    problem = build_routing_problem(state, depot_id)
    solution = optimizer.solve(problem)
    state.plan = {}
    for vid, solved in solution.routes.items():
        if not solved:
            continue
        stops = [
            Stop(customer_id=ss.customer_id, sequence=k,
                 planned_arrival=ss.arrival, planned_departure=ss.departure,
                 load_after_stop=ss.load_after)
            for k, ss in enumerate(solved, start=1)
        ]
        state.plan[vid] = VehicleRoute(
            vehicle_id=vid, stops=stops,
            total_time=solution.metrics.get("total_time_min", 0.0),
            start_time=stops[0].planned_arrival,
            end_time=stops[-1].planned_departure,
        )
    return solution.dropped
