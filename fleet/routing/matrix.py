"""Travel-time matrices for routing.

Dijkstra over the (directed, multi-edge) road graph using each edge's
`effective_time` as weight and `is_passable(wade_capability)` to skip
flooded/blocked edges. Parallel edges A->B are handled naturally: relaxing all
outgoing edges keeps the minimum. Pure + deterministic; no solver here."""

import heapq
from typing import Dict, List

from fleet.contracts.state import RoadGraph

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
