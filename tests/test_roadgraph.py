from datetime import datetime

from fleet.contracts.state import (
    RoadGraph, RoadNode, RoadEdge, Location, EdgeStatus, WorldState, Depot,
)


def _two_node_graph():
    a = Location(0.0, 0.0, "", "A")
    b = Location(1.0, 1.0, "", "B")
    e1 = RoadEdge("A", "B", 2.0, 10.0)                       # id -> "A->B"
    e2 = RoadEdge("A", "B", 1.5, 7.0, id="A->B#2",
                  status=EdgeStatus.FLOODED, flood_level=0.5)
    graph = RoadGraph(
        nodes={"A": RoadNode("A", a), "B": RoadNode("B", b)},
        edges={e1.id: e1, e2.id: e2},
        adjacency={"A": ["A->B", "A->B#2"], "B": []},
    )
    return graph, e1, e2


def test_parallel_edges_between_same_pair():
    graph, e1, e2 = _two_node_graph()
    between = graph.edges_between("A", "B")
    assert len(between) == 2
    assert {e.id for e in between} == {"A->B", "A->B#2"}


def test_out_edges_uses_adjacency_index():
    graph, e1, e2 = _two_node_graph()
    assert {e.id for e in graph.out_edges("A")} == {"A->B", "A->B#2"}
    assert graph.out_edges("B") == []


def test_get_edge_by_id():
    graph, e1, e2 = _two_node_graph()
    assert graph.get_edge("A->B#2") is e2
    assert graph.get_edge("does-not-exist") is None


def test_round_trip_preserves_parallel_edges():
    graph, _e1, _e2 = _two_node_graph()
    t0 = datetime(2026, 6, 5, 6, 0)
    state = WorldState(clock=t0,
                       depot=Depot(Location(0, 0, "", "d"), {}, t0, t0),
                       road_graph=graph)
    snapshot = state.to_dict()
    restored = WorldState.from_dict(snapshot)
    assert restored.to_dict() == snapshot
    assert len(restored.road_graph.edges_between("A", "B")) == 2
