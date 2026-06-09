"""Travel-time matrices for routing.

Dijkstra over the (directed, multi-edge) road graph using each edge's
`effective_time` as weight and `is_passable(wade_capability)` to skip
flooded/blocked edges. Parallel edges A->B are handled naturally: relaxing all
outgoing edges keeps the minimum. Pure + deterministic; no solver here."""

import heapq
from typing import Dict, List

from fleet.contracts.state import RoadGraph, WorldState, VehicleStatus
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
                        wade_capability: float) -> List[str]:
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
            if not edge.is_passable(wade_capability):
                continue
            nd = d + edge.effective_time
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


def build_time_matrix(graph: RoadGraph, locations: List[str],
                      wade_capability: float) -> List[List[float]]:
    """N×N travel-time matrix (minutes) over `locations`, indexed by position in
    the list. `matrix[i][j]` = shortest time from locations[i] to locations[j]
    for a vehicle of the given wade capability; INF if unreachable."""
    n = len(locations)
    pos = {loc: i for i, loc in enumerate(locations)}
    matrix = [[INF] * n for _ in range(n)]
    for i, src in enumerate(locations):
        matrix[i][i] = 0.0
        for loc, t in shortest_times_from(graph, src, wade_capability).items():
            if loc in pos:
                matrix[i][pos[loc]] = t
    return matrix


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

    # broken / in-maintenance vehicles can't take new work -> excluded from the solve.
    available = [v for v in state.vehicles.values()
                 if v.status not in (VehicleStatus.BROKEN, VehicleStatus.MAINTENANCE)]

    def _current_node(v) -> str:
        r = state.plan.get(v.id)
        if not r or not r.stops:
            return depot_id
        visited = [st for st in r.stops if st.actual_arrival is not None]
        if not visited:
            return depot_id
        return max(visited, key=lambda st: st.sequence).customer_id

    starts = {v.id: _current_node(v) for v in available}
    extra = [n for n in dict.fromkeys(starts.values())
             if n != depot_id and n not in pending]
    locations = [depot_id] + extra + pending

    by_type: Dict[str, list] = {}
    for v in available:
        by_type.setdefault(v.veh_type, []).append(v)
    time_matrix = {
        vt: build_time_matrix(state.road_graph, locations,
                              min(v.wade_capability for v in vs))
        for vt, vs in by_type.items()
    }

    fleet = [
        FleetVehicleSpec(
            id=v.id, capacity_kg=v.capacity_kg, veh_type=v.veh_type,
            shift_start=v.shift_start or state.depot.opening_time,
            shift_end=v.shift_end or state.depot.closing_time,
            start_node=starts[v.id],
        )
        for v in available
    ]

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
