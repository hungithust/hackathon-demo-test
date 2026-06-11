import networkx as nx
import pytest

from fleet.geo.router import RouteGeometry, nearest_node, route


def _line_graph():
    """3 nodes in a row; two edges of 1000 m / 120 s each."""
    g = nx.DiGraph()
    g.add_node(1, y=10.0000, x=106.0000)
    g.add_node(2, y=10.0000, x=106.0010)
    g.add_node(3, y=10.0000, x=106.0020)
    g.add_edge(1, 2, length=1000.0, travel_time=120.0)
    g.add_edge(2, 3, length=1000.0, travel_time=120.0)
    return g


def test_nearest_node_picks_closest():
    g = _line_graph()
    assert nearest_node(g, 10.0000, 106.0019) == 3
    assert nearest_node(g, 10.0000, 106.0001) == 1


def test_route_sums_length_time_and_builds_polyline():
    g = _line_graph()
    r = route(g, (10.0, 106.0), (10.0, 106.0020))
    assert isinstance(r, RouteGeometry)
    assert r.distance_km == pytest.approx(2.0)
    assert r.minutes == pytest.approx(4.0)
    assert r.polyline == [(10.0, 106.0), (10.0, 106.001), (10.0, 106.002)]


def test_route_disconnected_falls_back_to_straight_line():
    g = _line_graph()
    g.add_node(9, y=11.0, x=107.0)            # isolated; no path from the row
    r = route(g, (10.0, 106.0), (11.0, 107.0), urban_speed_kmh=25.0)
    assert len(r.polyline) == 2                # straight line endpoints
    assert r.distance_km > 0 and r.minutes > 0
