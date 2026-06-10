"""Orchestrates planning: build the problem, solve it, and write the resulting
routes into state.plan. Returns the dropped customer ids (candidates for DEFER).

Keeps the loop/agent decoupled from the optimizer impl: they call plan_routes
with whichever RouteOptimizer the factory selected."""

import datetime
from typing import List, Tuple, Dict, Optional

from fleet.contracts.state import WorldState, VehicleRoute, Stop
from fleet.contracts.interfaces import RouteOptimizer
from fleet.routing.matrix import (
    build_routing_problem, shortest_times_from, build_time_matrix,
    build_multi_route_matrices, ROUTE_PROFILES,
)


def _build_plan(state: WorldState, optimizer: RouteOptimizer,
                depot_id: str = "DEPOT") -> Tuple[List[str], Dict[str, VehicleRoute]]:
    problem = build_routing_problem(state, depot_id)
    solution = optimizer.solve(problem)
    new_plan = {}
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
        vehicle = state.get_vehicle(vid)
        wade = float(vehicle.wade_capability) if vehicle else 0.3
        
        first_leg_min = shortest_times_from(state.road_graph, depot_id, wade).get(stops[0].customer_id, 0.0)
        last_leg_min = shortest_times_from(state.road_graph, stops[-1].customer_id, wade).get(depot_id, 0.0)
        
        start_time = stops[0].planned_arrival - __import__("datetime").timedelta(minutes=first_leg_min)
        
        new_plan[vid] = VehicleRoute(
            vehicle_id=vid, stops=stops,
            total_time=solution.metrics.get("total_time_min", 0.0),
            start_time=start_time,
            end_time=stops[-1].planned_departure + __import__("datetime").timedelta(minutes=last_leg_min),
        )
    return solution.dropped, new_plan


def plan_routes(state: WorldState, optimizer: RouteOptimizer,
                depot_id: str = "DEPOT") -> List[str]:
    dropped, state.plan = _build_plan(state, optimizer, depot_id)
    return dropped


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


def preview_reroute(state: WorldState, optimizer: RouteOptimizer,
                    depot_id: str = "DEPOT") -> Tuple[List[str], Dict[str, VehicleRoute]]:
    old_plan = {vid: route for vid, route in state.plan.items()}
    dropped, new_plan = _build_plan(state, optimizer, depot_id)
    
    for vid, new_route in new_plan.items():
        if vid in old_plan:
            old_route = old_plan[vid]
            visited_stops = [s for s in old_route.stops if s.actual_arrival is not None]
            
            if visited_stops and getattr(visited_stops[-1], "actual_departure", None):
                unvisited = [s for s in old_route.stops if s.actual_arrival is None]
                if unvisited:
                    import copy
                    from datetime import timedelta
                    nxt = copy.deepcopy(unvisited[0])
                    v = state.get_vehicle(vid)
                    wade = float(v.wade_capability) if v else 0.3
                    dist = shortest_times_from(state.road_graph, visited_stops[-1].customer_id, wade)
                    leg_min = dist.get(nxt.customer_id, 0.0)
                    nxt.planned_arrival = visited_stops[-1].actual_departure + timedelta(minutes=leg_min)
                    svc = float(getattr(state.customers.get(nxt.customer_id), "service_time_min", 10.0))
                    nxt.planned_departure = nxt.planned_arrival + timedelta(minutes=svc)
                    visited_stops.append(nxt)
            elif not visited_stops and old_route.stops and getattr(old_route, "start_time", None) and state.clock > old_route.start_time:
                import copy
                from datetime import timedelta
                nxt = copy.deepcopy(old_route.stops[0])
                v = state.get_vehicle(vid)
                wade = float(v.wade_capability) if v else 0.3
                dist = shortest_times_from(state.road_graph, depot_id, wade)
                leg_min = dist.get(nxt.customer_id, 0.0)
                nxt.planned_arrival = old_route.start_time + timedelta(minutes=leg_min)
                svc = float(getattr(state.customers.get(nxt.customer_id), "service_time_min", 10.0))
                nxt.planned_departure = nxt.planned_arrival + timedelta(minutes=svc)
                visited_stops.append(nxt)
            
            if visited_stops:
                for i, s in enumerate(visited_stops, start=1):
                    s.sequence = i
                for i, s in enumerate(new_route.stops, start=len(visited_stops) + 1):
                    s.sequence = i
                new_route.stops = visited_stops + new_route.stops
                
            if visited_stops or state.clock > old_route.start_time:
                new_route.start_time = old_route.start_time
                
    for vid, old_route in old_plan.items():
        if vid not in new_plan:
            visited_stops = [s for s in old_route.stops if s.actual_arrival is not None]
            v = state.get_vehicle(vid)
            wade = float(v.wade_capability) if v else 0.3
            
            if visited_stops:
                leg_min = shortest_times_from(state.road_graph, visited_stops[-1].customer_id, wade).get(depot_id, 0.0)
                new_plan[vid] = VehicleRoute(
                    vehicle_id=vid,
                    stops=visited_stops,
                    total_time=old_route.total_time,
                    start_time=visited_stops[0].planned_arrival,
                    end_time=visited_stops[-1].actual_departure + __import__("datetime").timedelta(minutes=leg_min)
                )
            elif state.clock > old_route.start_time and old_route.stops:
                first_stop = old_route.stops[0]
                leg_min = shortest_times_from(state.road_graph, first_stop.customer_id, wade).get(depot_id, 0.0)
                new_plan[vid] = VehicleRoute(
                    vehicle_id=vid,
                    stops=[first_stop],
                    total_time=old_route.total_time,
                    start_time=old_route.start_time,
                    end_time=first_stop.actual_departure + __import__("datetime").timedelta(minutes=leg_min) if getattr(first_stop, "actual_departure", None) else first_stop.planned_arrival + __import__("datetime").timedelta(minutes=leg_min)
                )

    return dropped, new_plan


def reroute(state: WorldState, optimizer: RouteOptimizer,
            depot_id: str = "DEPOT") -> List[str]:
    dropped, new_plan = preview_reroute(state, optimizer, depot_id)
    state.plan = new_plan
    return dropped


# ---------------------------------------------------------------------------
# Targeted rerouting: only for vehicles affected by a specific disruption
# ---------------------------------------------------------------------------

def build_reroute_problem_for_vehicle(
        state: WorldState, vehicle_id: str,
        depot_id: str = "DEPOT"):
    """Build a single-vehicle RoutingProblem starting from the vehicle's current
    position with its remaining (unvisited) originally-assigned stops as tasks.

    This satisfies req 5: current position = start ("depot"), original assigned
    stops = destinations.  The cost matrix reflects the current road graph so the
    solver naturally routes around high-cost (congested/flooded) edges.
    Returns None when the vehicle has no pending work."""
    from fleet.contracts.dto import RoutingProblem, FleetVehicleSpec, TaskSpec

    vehicle = state.get_vehicle(vehicle_id)
    if not vehicle:
        return None
    vr = state.plan.get(vehicle_id)
    if not vr:
        return None

    visited = sorted([s for s in vr.stops if s.actual_arrival is not None],
                     key=lambda s: s.sequence)
    unvisited = [s for s in vr.stops if s.actual_arrival is None]
    if not unvisited:
        return None

    is_driving = False
    if visited:
        last = visited[-1]
        if last.actual_departure and state.clock >= last.actual_departure:
            is_driving = True
    # No visited stops → vehicle still at/near DEPOT, allow full re-plan from DEPOT

    if is_driving:
        locked_stop = unvisited[0]
        current_loc = locked_stop.customer_id
        avail_time = max(locked_stop.planned_departure, state.clock)
        unvisited = unvisited[1:]
    else:
        if visited:
            current_loc = visited[-1].customer_id
            avail_time = visited[-1].actual_departure or (
                visited[-1].actual_arrival + datetime.timedelta(minutes=10.0))
        else:
            current_loc = depot_id
            avail_time = vehicle.shift_start or state.depot.opening_time
        avail_time = max(avail_time, state.clock)

    if not unvisited:
        return None

    # Locations list: [current_loc] + unvisited customers + DEPOT (return point)
    locs: List[str] = [current_loc]
    for s in unvisited:
        if s.customer_id not in locs:
            locs.append(s.customer_id)
    if depot_id not in locs:
        locs.append(depot_id)

    wade = float(vehicle.wade_capability)

    # Single high-avoidance matrix: 100x extra cost on congested edges forces
    # the solver to route around traffic jams/flooded areas rather than through them.
    # Multi-profile approach was flawed: cuOpt always chose profile-0 (lowest cost).
    time_matrix = {
        f"{vehicle.veh_type}_reroute": build_time_matrix(
            state.road_graph, locs, wade, extra_congestion_factor=100.0)
    }

    tasks = []
    total_demand = 0.0
    for s in unvisited:
        c = state.customers.get(s.customer_id)
        if c:
            demand = float(sum(c.orders.values()))
            total_demand += demand
            tasks.append(TaskSpec(
                customer_id=s.customer_id,
                demand_kg=demand,
                # Clamp to avail_time so _base_time(problem)=state.clock; without this
                # planned_arrivals land in the past and the simulator instantly delivers them.
                tw_start=max(c.time_window.start, avail_time),
                tw_end=c.time_window.end,
                service_time_min=float(getattr(c, "service_time_min", 10.0)),
                priority=c.priority,
            ))

    if not tasks:
        return None

    # Single vehicle with the reroute matrix (oversized capacity to serve all stops).
    fleet = [
        FleetVehicleSpec(
            id=f"{vehicle_id}__reroute",
            capacity_kg=max(vehicle.capacity_kg, total_demand + 1.0),
            veh_type=f"{vehicle.veh_type}_reroute",
            shift_start=avail_time,
            shift_end=vehicle.shift_end or state.depot.closing_time,
            start_location=current_loc,
        )
    ]

    return RoutingProblem(
        locations=locs,
        depot_id=depot_id,
        time_matrix=time_matrix,
        fleet=fleet,
        tasks=tasks,
    )


def preview_reroute_affected(
        state: WorldState, optimizer: RouteOptimizer,
        affected_vehicle_ids: List[str],
        depot_id: str = "DEPOT") -> Tuple[List[str], Dict[str, VehicleRoute]]:
    """Compute new routes for *only* the affected vehicles without touching the
    rest of the plan.  Each vehicle starts from its current position and visits
    its original remaining stops via whatever alternative roads now exist (the
    cost matrix already penalises congested/flooded edges heavily).

    Returns (dropped_customer_ids, proposed_routes_for_affected_vehicles).
    The caller merges proposed_routes into state.plan selectively."""
    proposed: Dict[str, VehicleRoute] = {}
    all_dropped: List[str] = []

    for vid in affected_vehicle_ids:
        problem = build_reroute_problem_for_vehicle(state, vid, depot_id)
        if problem is None:
            continue

        try:
            solution = optimizer.solve(problem)
        except Exception as exc:
            print(f"[reroute_affected] solver error for {vid}: {exc}")
            continue

        all_dropped.extend(solution.dropped)

        # Single virtual vehicle keyed "{vid}__reroute".
        virtual_id = f"{vid}__reroute"
        merged_solved = list(solution.routes.get(virtual_id, []))
        merged_solved.sort(key=lambda ss: ss.arrival)

        print(f"[reroute_affected] {vid}: reroute profile -> {len(merged_solved)} stops")

        if not merged_solved:
            continue

        vehicle = state.get_vehicle(vid)
        wade = float(vehicle.wade_capability) if vehicle else 0.3
        vr = state.plan[vid]
        visited = sorted([s for s in vr.stops if s.actual_arrival is not None],
                         key=lambda s: s.sequence)
        unvisited = sorted([s for s in vr.stops if s.actual_arrival is None],
                           key=lambda s: s.sequence)

        is_driving = False
        if visited:
            last = visited[-1]
            if last.actual_departure and state.clock >= last.actual_departure:
                is_driving = True
        # No visited stops → vehicle still at/near DEPOT, allow full re-plan

        locked_stops = []
        if is_driving and unvisited:
            locked_stops = [unvisited[0]]

        offset = len(visited) + len(locked_stops)

        # Re-timestamp: walk stops in merged order, computing actual leg times
        # from the previous location using the most avoidant matrix (factor=100).
        current_loc = locked_stops[0].customer_id if locked_stops else (
            visited[-1].customer_id if visited else depot_id)
        current_time = max(
            locked_stops[0].planned_departure if locked_stops else (
                visited[-1].actual_departure
                if visited and visited[-1].actual_departure
                else (visited[-1].actual_arrival + datetime.timedelta(minutes=10.0)
                      if visited else problem.fleet[0].shift_start)
            ),
            state.clock,
        )

        new_stops: List[Stop] = []
        for k, ss in enumerate(merged_solved, start=1):
            dist = shortest_times_from(state.road_graph, current_loc, wade)
            leg_min = dist.get(ss.customer_id, 1.0)
            arrival = current_time + datetime.timedelta(minutes=leg_min)
            c = state.customers.get(ss.customer_id)
            svc = float(getattr(c, "service_time_min", 10.0)) if c else 10.0
            departure = arrival + datetime.timedelta(minutes=svc)
            new_stops.append(Stop(
                customer_id=ss.customer_id,
                sequence=offset + k,
                planned_arrival=arrival,
                planned_departure=departure,
                load_after_stop=ss.load_after,
                demand_kg=float(sum(c.orders.values())) if c else 0.0,
            ))
            current_loc = ss.customer_id
            current_time = departure

        last_leg_min = shortest_times_from(
            state.road_graph, current_loc, wade).get(depot_id, 0.0)

        proposed[vid] = VehicleRoute(
            vehicle_id=vid,
            stops=visited + locked_stops + new_stops,
            total_time=solution.metrics.get("total_time_min", 0.0),
            start_time=vr.start_time,
            end_time=(new_stops[-1].planned_departure
                      + datetime.timedelta(minutes=last_leg_min))
                     if new_stops else vr.end_time,
        )

    return all_dropped, proposed

