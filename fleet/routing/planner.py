"""Orchestrates planning: build the problem, solve it, and write the resulting
routes into state.plan. Returns the dropped customer ids (candidates for DEFER).

Keeps the loop/agent decoupled from the optimizer impl: they call plan_routes
with whichever RouteOptimizer the factory selected."""

import datetime
import heapq
from typing import List, Tuple, Dict, Optional

from fleet.contracts.state import WorldState, VehicleRoute, Stop, EdgeStatus
from fleet.contracts.interfaces import RouteOptimizer
from fleet.routing.matrix import (
    build_routing_problem, shortest_times_from, build_time_matrix,
    build_multi_route_matrices, ROUTE_PROFILES,
    avoidance_times_from, shortest_times_from_virtual,
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
# Graph-based rerouting helpers (no VRP solver — greedy nearest-neighbour)
# ---------------------------------------------------------------------------

_INF = float("inf")


def _vehicle_current_leg(
        state: WorldState, vehicle_id: str,
        depot_id: str = "DEPOT") -> Optional[Tuple[str, str, float]]:
    """Return (from_node, to_node, elapsed_min) when the vehicle is in transit
    between two planned locations, else None.

    elapsed_min is the time already spent on the current leg since the vehicle
    departed from_node. Used to locate the vehicle's physical position on the road
    and to decide whether it has entered a congested segment."""
    vehicle = state.get_vehicle(vehicle_id)
    vr = state.plan.get(vehicle_id)
    if not vehicle or not vr or not vr.stops:
        return None

    visited = sorted([s for s in vr.stops if s.actual_arrival is not None],
                     key=lambda s: s.sequence)
    unvisited = [s for s in vr.stops if s.actual_arrival is None]
    if not unvisited:
        return None

    if visited:
        last = visited[-1]
        if last.actual_departure is None:
            return None  # vehicle is still at a stop serving
        from_node = last.customer_id
        from_time = last.actual_departure
    elif vr.start_time and state.clock > vr.start_time:
        from_node = depot_id
        from_time = vr.start_time
    else:
        return None  # not yet departed

    to_node = unvisited[0].customer_id
    elapsed_min = (state.clock - from_time).total_seconds() / 60.0
    if elapsed_min <= 0:
        return None
    return from_node, to_node, elapsed_min


def _vehicle_in_jam(
        state: WorldState, vehicle_id: str,
        depot_id: str = "DEPOT") -> bool:
    """True when the vehicle has already entered the congested portion of its
    current edge and can no longer be rerouted.

    Uses the time-to-jam-start criterion: the uncongested section before the jam
    is traversed at base speed, so it takes congestion_start_frac × base_time
    minutes to reach the jam boundary. If elapsed_min >= that threshold, the
    vehicle is committed."""
    pos = _vehicle_current_leg(state, vehicle_id, depot_id)
    if pos is None:
        return False
    from_node, to_node, elapsed_min = pos
    for edge in state.road_graph.out_edges(from_node):
        if edge.to_node == to_node and edge.status == EdgeStatus.CONGESTED:
            time_to_jam_start = edge.congestion_start_frac * edge.base_time_minutes
            if elapsed_min >= time_to_jam_start:
                return True
    return False


def graph_reroute_vehicle(
        state: WorldState, vehicle_id: str,
        depot_id: str = "DEPOT") -> Optional[VehicleRoute]:
    """Greedy nearest-neighbour reroute for a single vehicle using Dijkstra
    with 100× avoidance on CONGESTED edges.

    Treats the vehicle's current on-road position as a virtual start node so
    edge costs are proportional to how much of each segment remains.  Returns
    None when the vehicle is already inside a jam (requirement 5) or has no
    pending work."""
    vehicle = state.get_vehicle(vehicle_id)
    vr = state.plan.get(vehicle_id)
    if not vehicle or not vr:
        return None

    visited = sorted([s for s in vr.stops if s.actual_arrival is not None],
                     key=lambda s: s.sequence)
    unvisited = sorted([s for s in vr.stops if s.actual_arrival is None],
                       key=lambda s: s.sequence)
    if not unvisited:
        return None

    # Req 5: vehicle already committed — do not reroute
    if _vehicle_in_jam(state, vehicle_id, depot_id):
        return None

    wade = float(vehicle.wade_capability)
    pos = _vehicle_current_leg(state, vehicle_id, depot_id)

    # A vehicle is "driving" — and therefore committed to its next stop — only
    # once it has actually served a customer. A vehicle that left DEPOT but has
    # not reached any customer yet is sent back to DEPOT on approval (see
    # SimulationController.approve), so it must re-plan freely from DEPOT with NO
    # locked first stop. Otherwise locking the original first stop forces the
    # vehicle back onto the jammed leg it was trying to avoid (it appears to keep
    # following the old route). This mirrors build_reroute_problem_for_vehicle.
    is_driving = bool(
        visited and visited[-1].actual_departure
        and state.clock >= visited[-1].actual_departure
    )

    # First unvisited stop is locked when the vehicle is already en route to it
    locked_stop: Optional[Stop] = None
    free_stops: List[Stop] = list(unvisited)
    if is_driving and unvisited:
        locked_stop = unvisited[0]
        free_stops = unvisited[1:]

    # Compute avoidance distances from the vehicle's planning origin: its current
    # on-road virtual position only while genuinely driving from a served stop;
    # otherwise from DEPOT (the vehicle returns there before re-planning).
    if is_driving and pos is not None:
        from_node, to_node, elapsed_min = pos
        curr_dists = shortest_times_from_virtual(
            state.road_graph, from_node, to_node, elapsed_min, wade,
            extra_congestion_factor=100.0)
        current_time = state.clock
    else:
        if visited:
            start_node = visited[-1].customer_id
            start_time = (visited[-1].actual_departure
                          or visited[-1].actual_arrival
                          + datetime.timedelta(minutes=10.0))
        else:
            start_node = depot_id
            start_time = vehicle.shift_start or state.depot.opening_time
        current_time = max(start_time, state.clock)
        curr_dists = avoidance_times_from(state.road_graph, start_node, wade)

    # ── Build ordered sequence ────────────────────────────────────────────────
    sequence: List[Stop] = []
    if locked_stop:
        sequence.append(locked_stop)

    remaining: Dict[str, Stop] = {s.customer_id: s for s in free_stops}

    # After the locked stop, continue greedy NN from there
    nn_dists = (avoidance_times_from(state.road_graph, locked_stop.customer_id, wade)
                if locked_stop
                else curr_dists)

    while remaining:
        best_cid = min(remaining, key=lambda cid: nn_dists.get(cid, _INF))
        if nn_dists.get(best_cid, _INF) >= _INF:
            # Unreachable: append in original sequence order
            for s in sorted(remaining.values(), key=lambda s: s.sequence):
                sequence.append(s)
            break
        sequence.append(remaining.pop(best_cid))
        nn_dists = avoidance_times_from(state.road_graph, best_cid, wade)

    # ── Timestamp each stop ───────────────────────────────────────────────────
    new_stops: List[Stop] = []
    offset = len(visited)
    timing_dists = curr_dists
    timing_time = current_time

    for k, s in enumerate(sequence, start=1):
        leg_min = timing_dists.get(s.customer_id, 1.0)
        arrival = timing_time + datetime.timedelta(minutes=leg_min)
        c = state.customers.get(s.customer_id)
        svc = float(getattr(c, "service_time_min", 10.0)) if c else 10.0
        departure = arrival + datetime.timedelta(minutes=svc)
        new_stops.append(Stop(
            customer_id=s.customer_id,
            sequence=offset + k,
            planned_arrival=arrival,
            planned_departure=departure,
            load_after_stop=s.load_after_stop,
            demand_kg=s.demand_kg,
        ))
        timing_time = departure
        timing_dists = avoidance_times_from(state.road_graph, s.customer_id, wade)

    if not new_stops:
        return None

    last_leg = timing_dists.get(depot_id, 0.0)
    return VehicleRoute(
        vehicle_id=vehicle_id,
        stops=visited + new_stops,
        total_time=0.0,
        start_time=vr.start_time,
        end_time=new_stops[-1].planned_departure + datetime.timedelta(minutes=last_leg),
    )


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
    """Compute new routes for *only* the affected vehicles using graph-based
    greedy nearest-neighbour (no VRP solver overhead).

    Vehicles already inside a congested segment are skipped (req 5).
    Each vehicle's virtual on-road position is used as the start so edge costs
    are proportional to the remaining distance (req 1).

    Returns (dropped_customer_ids, proposed_routes_for_affected_vehicles)."""
    proposed: Dict[str, VehicleRoute] = {}

    for vid in affected_vehicle_ids:
        new_route = graph_reroute_vehicle(state, vid, depot_id)
        if new_route is None:
            in_jam = _vehicle_in_jam(state, vid, depot_id)

            print(f"[reroute_affected] {vid}: {'already in jam - skipped' if in_jam else 'no pending work'}")
            continue
        print(f"[reroute_affected] {vid}: graph reroute -> {len([s for s in new_route.stops if s.actual_arrival is None])} stops remaining")
        proposed[vid] = new_route

    return [], proposed

