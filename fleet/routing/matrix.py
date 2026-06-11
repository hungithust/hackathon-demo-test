"""Travel-time matrices for routing.

Dijkstra over the (directed, multi-edge) road graph using each edge's
`effective_time` as weight and `is_passable(wade_capability)` to skip
flooded/blocked edges. Parallel edges A->B are handled naturally: relaxing all
outgoing edges keeps the minimum. Pure + deterministic; no solver here."""

import heapq
from contextlib import contextmanager
from typing import Dict, List

from fleet.contracts.state import RoadGraph, WorldState, VehicleStatus, EdgeStatus, RoadNode, RoadEdge, Location
from fleet.contracts.dto import RoutingProblem, FleetVehicleSpec, TaskSpec

DEFAULT_SERVICE_TIME_MIN = 10.0

INF = float("inf")


def shortest_times_from(graph: RoadGraph, source: str,
                        wade_capability: float) -> Dict[str, float]:
    """Min travel time (minutes) from `source` to every reachable node, for a
    vehicle that can wade up to `wade_capability` metres. Unreachable nodes are
    absent from the result."""
    dist: Dict[str, float] = {source: 0.0}
    pq: List = [(0.0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, INF):
            continue
        for edge in graph.out_edges(u):
            if not edge.is_passable(wade_capability):
                continue
            nd = d + edge.effective_time
            if nd < dist.get(edge.to_node, INF):
                dist[edge.to_node] = nd
                heapq.heappush(pq, (nd, edge.to_node))
    return dist


def shortest_path_edges(graph: RoadGraph, source: str, dest: str,
                        wade_capability: float, use_base: bool = False) -> List[str]:
    """Edge-id sequence of the min-time route source->dest for a vehicle of the
    given wade capability, or [] if dest is unreachable. Used to reconstruct the
    real road geometry a vehicle drives along (a leg may run through DEPOT)."""
    if source == dest:
        return []
    dist: Dict[str, float] = {source: 0.0}
    prev_edge: Dict[str, str] = {}
    pq: List = [(0.0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dest:
            break
        if d > dist.get(u, INF):
            continue
        for edge in graph.out_edges(u):
            if not use_base and not edge.is_passable(wade_capability):
                continue
            nd = d + (edge.base_time_minutes if use_base else edge.effective_time)
            if nd < dist.get(edge.to_node, INF):
                dist[edge.to_node] = nd
                prev_edge[edge.to_node] = edge.id
                heapq.heappush(pq, (nd, edge.to_node))
    if dest not in prev_edge:
        return []
    path: List[str] = []
    cur = dest
    while cur != source:
        eid = prev_edge.get(cur)
        if eid is None:
            return []
        edge = graph.get_edge(eid)
        path.append(eid)
        cur = edge.from_node
    path.reverse()
    return path


def avoidance_times_from(graph: RoadGraph, source: str,
                         wade_capability: float,
                         extra_congestion_factor: float = 100.0) -> Dict[str, float]:
    """Dijkstra from `source` with `extra_congestion_factor` × penalty on CONGESTED edges.
    Used for rerouting so the solver strongly avoids jammed roads."""
    dist: Dict[str, float] = {source: 0.0}
    pq: List = [(0.0, source)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, INF):
            continue
        for edge in graph.out_edges(u):
            if not edge.is_passable(wade_capability):
                continue
            cost = edge.effective_time
            if edge.status == EdgeStatus.CONGESTED:
                cost *= extra_congestion_factor
            nd = d + cost
            if nd < dist.get(edge.to_node, INF):
                dist[edge.to_node] = nd
                heapq.heappush(pq, (nd, edge.to_node))
    return dist


@contextmanager
def inject_virtual_node(
        graph: RoadGraph, cp_id: str, from_node: str, to_node: str,
        elapsed_min: float, wade_capability: float,
        extra_congestion_factor: float = 100.0):
    """Context manager to temporarily inject a virtual node `cp_id` into the graph
    representing the vehicle's physical position along the edge (from_node -> to_node)."""
    edge = None
    for e in graph.out_edges(from_node):
        if e.to_node == to_node and e.is_passable(wade_capability):
            if edge is None or e.effective_time < edge.effective_time:
                edge = e

    cost_to_from = elapsed_min
    if edge is None:
        cost_to_dest = INF
    else:
        cong_start_min = edge.congestion_start_frac * edge.base_time_minutes
        if elapsed_min <= cong_start_min:
            uncong_before = cong_start_min - elapsed_min
            cong_seg = (edge.congestion_end_frac - edge.congestion_start_frac) * edge.base_time_minutes
            cong_cost = cong_seg * edge.traffic_factor
            if extra_congestion_factor > 1.0 and edge.status == EdgeStatus.CONGESTED:
                cong_cost *= extra_congestion_factor
            after_cong = (1.0 - edge.congestion_end_frac) * edge.base_time_minutes
            cost_to_dest = (uncong_before + cong_cost + after_cong)
        else:
            cost_to_dest = max(0.0, edge.effective_time - elapsed_min)

        flood_pen = 100.0 if edge.flood_level > 0.0 else 1.0
        cost_to_dest *= flood_pen

    from_loc = graph.nodes[from_node].location if from_node in graph.nodes else Location(lat=0, lng=0, address="", name="")
    cp_node = RoadNode(id=cp_id, location=from_loc)
    graph.nodes[cp_id] = cp_node

    added_edges = []
    # Edge: cp -> from_node and from_node -> cp
    e_bf = RoadEdge(from_node=cp_id, to_node=from_node, distance_km=0, base_time_minutes=cost_to_from)
    e_bf.id = f"{cp_id}->{from_node}"
    e_fb = RoadEdge(from_node=from_node, to_node=cp_id, distance_km=0, base_time_minutes=cost_to_from)
    e_fb.id = f"{from_node}->{cp_id}"
    added_edges.extend([e_bf, e_fb])

    # Edge: cp -> to_node and to_node -> cp
    if cost_to_dest < INF:
        e_ft = RoadEdge(from_node=cp_id, to_node=to_node, distance_km=0, base_time_minutes=cost_to_dest)
        e_ft.id = f"{cp_id}->{to_node}"
        e_tf = RoadEdge(from_node=to_node, to_node=cp_id, distance_km=0, base_time_minutes=cost_to_dest)
        e_tf.id = f"{to_node}->{cp_id}"
        added_edges.extend([e_ft, e_tf])

    for e in added_edges:
        graph.edges[e.id] = e
        if e.from_node not in graph.adjacency:
            graph.adjacency[e.from_node] = []
        graph.adjacency[e.from_node].append(e.id)

    try:
        yield cp_id
    finally:
        del graph.nodes[cp_id]
        for e in added_edges:
            if e.id in graph.edges:
                del graph.edges[e.id]
            if e.from_node in graph.adjacency:
                if e.id in graph.adjacency[e.from_node]:
                    graph.adjacency[e.from_node].remove(e.id)

def shortest_times_from_virtual(
        graph: RoadGraph,
        from_node: str,
        to_node: str,
        elapsed_min: float,
        wade_capability: float,
        extra_congestion_factor: float = 100.0,
) -> Dict[str, float]:
    """Dijkstra from a virtual position `elapsed_min` minutes into edge (from_node->to_node)."""
    with inject_virtual_node(graph, "temp_cp", from_node, to_node, elapsed_min, wade_capability, extra_congestion_factor) as cp_id:
        dist = avoidance_times_from(graph, cp_id, wade_capability, extra_congestion_factor)
        # Remove cp_id from the returned dict so it behaves like a normal lookup
        if cp_id in dist:
            del dist[cp_id]
        return dist


def build_time_matrix(graph: RoadGraph, locations: List[str],
                      wade_capability: float,
                      extra_congestion_factor: float = 1.0) -> List[List[float]]:
    """N×N travel-time matrix (minutes) over `locations`, indexed by position in
    the list. `matrix[i][j]` = shortest time from locations[i] to locations[j]
    for a vehicle of the given wade capability; INF if unreachable.

    `extra_congestion_factor` multiplies the effective_time of congested edges on
    top of their existing traffic_factor, so a factor of 10 makes a congested edge
    10× more expensive relative to clear alternatives. Use this when building
    alternative route matrices (e.g. factor 1, 5, 25, 100 for 4 routing profiles)."""
    def _times(source: str) -> Dict[str, float]:
        if extra_congestion_factor == 1.0:
            return shortest_times_from(graph, source, wade_capability)
        # Custom Dijkstra with extra congestion penalty
        dist: Dict[str, float] = {source: 0.0}
        pq: List = [(0.0, source)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, INF):
                continue
            for edge in graph.out_edges(u):
                if not edge.is_passable(wade_capability):
                    continue
                cost = edge.effective_time
                if edge.status == EdgeStatus.CONGESTED:
                    cost *= extra_congestion_factor
                nd = d + cost
                if nd < dist.get(edge.to_node, INF):
                    dist[edge.to_node] = nd
                    heapq.heappush(pq, (nd, edge.to_node))
        return dist

    n = len(locations)
    pos = {loc: i for i, loc in enumerate(locations)}
    matrix = [[INF] * n for _ in range(n)]
    for i, src in enumerate(locations):
        matrix[i][i] = 0.0
        for loc, t in _times(src).items():
            if loc in pos:
                matrix[i][pos[loc]] = t
    return matrix


# Four congestion-avoidance profiles: route options with escalating traffic penalty.
# Profile 0 = base effective_time; profile 3 = 100x extra on congested edges
# (beyond existing traffic_factor=8, so 800x base → any detour shorter wins).
ROUTE_PROFILES = [1.0, 5.0, 25.0, 100.0]


def build_multi_route_matrices(graph: RoadGraph, locations: List[str],
                               wade_capability: float,
                               veh_type: str) -> Dict[str, List[List[float]]]:
    """Build 4 cost matrices (one per route profile) keyed as '{veh_type}_{i}'.
    cuOpt receives all 4 via cost_matrix_data so it can route vehicles differently
    depending on their assigned profile."""
    return {
        f"{veh_type}_r{i}": build_time_matrix(graph, locations, wade_capability, factor)
        for i, factor in enumerate(ROUTE_PROFILES)
    }


def build_routing_problem(state: WorldState,
                          depot_id: str = "DEPOT") -> RoutingProblem:
    """Assemble a solver-ready RoutingProblem from the current world.

    - locations: depot first, then customers that still have pending orders.
    - time_matrix: one N×N matrix per veh_type, using the minimum wade_capability
      among that type's vehicles (conservative: passable by every such vehicle).
    - fleet: one FleetVehicleSpec per vehicle (shift falls back to depot hours).
    - tasks: one TaskSpec per pending customer (demand_kg = total order units).
    """
    pending = [cid for cid in sorted(state.customers)
               if sum(state.customers[cid].orders.values()) > 0]
    locations = [depot_id] + pending

    # broken / in-maintenance vehicles can't take new work -> excluded from the solve.
    available = [v for v in state.vehicles.values()
                 if v.status not in (VehicleStatus.BROKEN, VehicleStatus.MAINTENANCE)]

    from datetime import timedelta
    
    fleet_params = []
    for v in available:
        start_loc = depot_id
        avail_time = v.shift_start or state.depot.opening_time
        
        if v.route and v.route.stops:
            visited = [s for s in v.route.stops if s.actual_arrival is not None]
        else:
            visited = []

        if visited:
            visited.sort(key=lambda s: s.sequence)
            last = visited[-1]
            start_loc = last.customer_id
            if getattr(last, "actual_departure", None):
                unvisited = [s for s in v.route.stops if s.actual_arrival is None]
                if unvisited:
                    nxt = unvisited[0]
                    start_loc = nxt.customer_id
                    from datetime import timedelta
                    dist = shortest_times_from(state.road_graph, last.customer_id, float(v.wade_capability))
                    leg_min = dist.get(nxt.customer_id, 0.0)
                    avail_time = max(avail_time, last.actual_departure + timedelta(minutes=leg_min))
                    cust = state.customers.get(start_loc)
                else:
                    avail_time = max(avail_time, last.actual_departure)
            else:
                cust = state.customers.get(start_loc)
                svc = float(getattr(cust, "service_time_min", 10.0)) if cust else 10.0
                avail_time = max(avail_time, last.actual_arrival + __import__("datetime").timedelta(minutes=svc))
        else:
            if v.route and v.route.stops:
                # Vehicle might be en route to its first stop
                first_stop = v.route.stops[0]
                from datetime import timedelta
                dist = shortest_times_from(state.road_graph, depot_id, float(v.wade_capability))
                if first_stop.customer_id in dist:
                    dep_time = first_stop.planned_arrival - timedelta(minutes=dist[first_stop.customer_id])
                    if state.clock > dep_time:
                        start_loc = first_stop.customer_id
                        leg_min = dist[first_stop.customer_id]
                        avail_time = max(avail_time, dep_time + timedelta(minutes=leg_min))
                        cust = state.customers.get(start_loc)
                    else:
                        avail_time = max(avail_time, dep_time)
                else:
                    avail_time = max(avail_time, state.clock)
            else:
                # Vehicle hasn't left depot yet; it cannot start its shift in the past.
                avail_time = max(avail_time, state.clock)
        
        fleet_params.append({
            "id": v.id, "capacity_kg": v.capacity_kg, "veh_type": v.veh_type,
            "shift_start": avail_time, "shift_end": v.shift_end or state.depot.closing_time,
            "start_location": start_loc
        })

    # Ensure all start locations are in the problem locations
    for p in fleet_params:
        if p["start_location"] not in locations:
            locations.append(p["start_location"])

    by_type: Dict[str, list] = {}
    for v in available:
        by_type.setdefault(v.veh_type, []).append(v)
    time_matrix = {
        vt: build_time_matrix(state.road_graph, locations,
                              min(v.wade_capability for v in vs))
        for vt, vs in by_type.items()
    }

    fleet = [FleetVehicleSpec(**p) for p in fleet_params]

    tasks = []
    for cid in pending:
        c = state.customers[cid]
        tasks.append(TaskSpec(
            customer_id=cid,
            demand_kg=float(sum(c.orders.values())),
            tw_start=c.time_window.start, tw_end=c.time_window.end,
            service_time_min=float(getattr(c, "service_time_min", DEFAULT_SERVICE_TIME_MIN)),
            priority=c.priority,
        ))

    return RoutingProblem(locations=locations, depot_id=depot_id,
                          time_matrix=time_matrix, fleet=fleet, tasks=tasks)
