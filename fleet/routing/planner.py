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
                 load_after_stop=ss.load_after,
                 demand_kg=float(sum(state.customers[ss.customer_id].orders.values()))
                 if ss.customer_id in state.customers else 0.0)
            for k, ss in enumerate(solved, start=1)
        ]
        state.plan[vid] = VehicleRoute(
            vehicle_id=vid, stops=stops,
            total_time=solution.metrics.get("total_time_min", 0.0),
            start_time=stops[0].planned_arrival,
            end_time=stops[-1].planned_departure,
        )
    return solution.dropped


def plan_total_minutes(state: WorldState) -> float:
    """Total planned drive time across the current plan (sum of each route's
    start->end span, minutes). Used to measure the *realized* delay a reroute
    introduces, so the UI shows a real number instead of the LLM's self-estimate."""
    total = 0.0
    for route in state.plan.values():
        if route.start_time is None or route.end_time is None:
            continue
        total += (route.end_time - route.start_time).total_seconds() / 60.0
    return total


def route_minutes_by_vehicle(state: WorldState) -> dict:
    """Planned drive minutes per vehicle in the current plan."""
    out = {}
    for vid, r in state.plan.items():
        if r.start_time is None or r.end_time is None:
            continue
        out[vid] = (r.end_time - r.start_time).total_seconds() / 60.0
    return out


def reroute_delay_minutes(before: dict, after: dict) -> float:
    """Total change in planned drive minutes across the fleet (sum over the union
    of vehicles). Positive = the reroute added delay; reported as-is (not clamped)."""
    keys = set(before) | set(after)
    return round(sum(after.get(k, 0.0) - before.get(k, 0.0) for k in keys), 1)


def reroute(state: WorldState, optimizer: RouteOptimizer,
            depot_id: str = "DEPOT") -> List[str]:
    """Re-solve from scratch against the current road graph. Because the time
    matrix is rebuilt from live edge statuses, a blocked/flooded edge is already
    excluded and the routes adapt automatically. Returns dropped customer ids.

    Already-completed deliveries are preserved: any stop the new plan re-emits for
    a customer that was already visited keeps its actual arrival/departure, so an
    in-progress run is never silently reset to "not yet delivered"."""
    visited = {
        s.customer_id: (s.actual_arrival, s.actual_departure)
        for route in state.plan.values() for s in route.stops
        if s.actual_arrival is not None
    }
    dropped = plan_routes(state, optimizer, depot_id)
    if visited:
        for route in state.plan.values():
            for s in route.stops:
                if s.customer_id in visited:
                    s.actual_arrival, s.actual_departure = visited[s.customer_id]
    return dropped
