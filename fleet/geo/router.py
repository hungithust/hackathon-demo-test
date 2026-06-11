"""Pure routing over a networkx graph: snap lat/lng to nearest node, shortest path
by edge `length`, sum `length`/`travel_time`, return the node polyline. No osmnx,
no I/O — testable with a tiny hand-built graph. Straight-line fallback when there
is no path so a bad coordinate degrades gracefully."""

import math
from dataclasses import dataclass
from typing import List, Tuple

import networkx as nx

LatLng = Tuple[float, float]


@dataclass(frozen=True)
class RouteGeometry:
    distance_km: float
    minutes: float
    polyline: List[LatLng]          # [(lat, lng), ...] along the route


def _haversine_km(a: LatLng, b: LatLng) -> float:
    r = 6371.0
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def nearest_node(graph, lat: float, lng: float):
    best, best_d = None, float("inf")
    for n, data in graph.nodes(data=True):
        d = (data["y"] - lat) ** 2 + (data["x"] - lng) ** 2
        if d < best_d:
            best_d, best = d, n
    return best


def _path_metrics(graph, path) -> Tuple[float, float]:
    """Sum length (m) and travel_time (s) along a node path, picking the shortest
    parallel edge in a MultiGraph."""
    length_m = time_s = 0.0
    multi = graph.is_multigraph()
    for u, v in zip(path[:-1], path[1:]):
        if multi:
            data = min(graph[u][v].values(), key=lambda d: d.get("length", 1e18))
        else:
            data = graph[u][v]
        length_m += float(data.get("length", 0.0))
        time_s += float(data.get("travel_time", 0.0))
    return length_m, time_s


def _straight_line(src: LatLng, dst: LatLng, urban_speed_kmh: float) -> RouteGeometry:
    km = _haversine_km(src, dst)
    return RouteGeometry(km, km / urban_speed_kmh * 60.0, [src, dst])


def route(graph, src: LatLng, dst: LatLng,
          urban_speed_kmh: float = 25.0) -> RouteGeometry:
    o, d = nearest_node(graph, *src), nearest_node(graph, *dst)
    if o is None or d is None:
        return _straight_line(src, dst, urban_speed_kmh)
    try:
        path = nx.shortest_path(graph, o, d, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return _straight_line(src, dst, urban_speed_kmh)
    if len(path) < 2:
        return _straight_line(src, dst, urban_speed_kmh)
    length_m, time_s = _path_metrics(graph, path)
    poly = [(graph.nodes[n]["y"], graph.nodes[n]["x"]) for n in path]
    km = length_m / 1000.0
    minutes = time_s / 60.0 if time_s > 0 else km / urban_speed_kmh * 60.0
    return RouteGeometry(km, minutes, poly)
