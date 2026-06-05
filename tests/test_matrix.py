from fleet.contracts.state import RoadGraph, RoadNode, RoadEdge, Location, EdgeStatus
from fleet.routing.matrix import shortest_times_from, INF


def _graph(edges):
    """Build a RoadGraph from a list of RoadEdge (nodes + adjacency inferred)."""
    nodes, adjacency, edict = {}, {}, {}
    for e in edges:
        for n in (e.from_node, e.to_node):
            nodes.setdefault(n, RoadNode(n, Location(0, 0, "", n)))
            adjacency.setdefault(n, [])
        edict[e.id] = e
        adjacency[e.from_node].append(e.id)
    return RoadGraph(nodes=nodes, edges=edict, adjacency=adjacency)


def test_dijkstra_simple_path():
    g = _graph([RoadEdge("A", "B", 1, 10), RoadEdge("B", "C", 1, 5)])
    dist = shortest_times_from(g, "A", wade_capability=1.0)
    assert dist["A"] == 0.0
    assert dist["B"] == 10.0
    assert dist["C"] == 15.0


def test_dijkstra_picks_min_parallel_edge():
    g = _graph([
        RoadEdge("A", "B", 2, 10),
        RoadEdge("A", "B", 1, 6, id="A->B#2"),
    ])
    assert shortest_times_from(g, "A", 1.0)["B"] == 6.0


def test_dijkstra_excludes_flooded_edge_for_low_wade():
    g = _graph([
        RoadEdge("A", "B", 2, 10),
        RoadEdge("A", "B", 1, 6, id="A->B#2",
                 status=EdgeStatus.FLOODED, flood_level=0.5),
    ])
    assert shortest_times_from(g, "A", 0.3)["B"] == 10.0   # cannot wade -> slow route
    assert shortest_times_from(g, "A", 0.6)["B"] == 6.0    # can wade -> fast route


def test_dijkstra_excludes_blocked_edge_for_all():
    g = _graph([RoadEdge("A", "B", 1, 5, status=EdgeStatus.BLOCKED)])
    assert shortest_times_from(g, "A", 99.0).get("B", INF) == INF


def test_dijkstra_uses_traffic_factor_in_weight():
    g = _graph([RoadEdge("A", "B", 1, 10, traffic_factor=3.0)])
    assert shortest_times_from(g, "A", 1.0)["B"] == 30.0


def test_dijkstra_unreachable_node_absent():
    g = _graph([RoadEdge("A", "B", 1, 5)])
    assert "Z" not in shortest_times_from(g, "A", 1.0)


from fleet.routing.matrix import build_time_matrix
from fleet.scenarios import build_sample_state

_SAMPLE_LOCS = ["DEPOT", "C001", "C002", "C003", "C004"]


def test_matrix_diagonal_zero_and_directed():
    g = _graph([RoadEdge("A", "B", 1, 10)])   # only A->B
    m = build_time_matrix(g, ["A", "B"], 1.0)
    assert m[0][0] == 0.0 and m[1][1] == 0.0
    assert m[0][1] == 10.0      # A->B
    assert m[1][0] == INF       # no B->A edge


def test_matrix_on_sample_excludes_flood_route_for_truck():
    m = build_time_matrix(build_sample_state().road_graph, _SAMPLE_LOCS, 0.3)
    # flooded DEPOT->C001#2 (6 min) impassable for wade 0.3 -> use the 10-min edge
    assert m[0][1] == 10.0


def test_matrix_on_sample_uses_flood_shortcut_for_amphibious():
    m = build_time_matrix(build_sample_state().road_graph, _SAMPLE_LOCS, 0.6)
    assert m[0][1] == 6.0       # can wade -> faster flooded shortcut
