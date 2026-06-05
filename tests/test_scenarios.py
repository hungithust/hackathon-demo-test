from fleet.contracts.state import WorldState, VehicleStatus
from fleet.scenarios import build_sample_state


def test_sample_shape():
    s = build_sample_state()
    assert isinstance(s, WorldState)
    assert len(s.vehicles) == 3
    assert len(s.customers) == 4
    assert s.depot.inventory  # non-empty


def test_sample_starts_at_depot():
    s = build_sample_state()
    assert all(v.status == VehicleStatus.AT_DEPOT for v in s.vehicles.values())
    assert all(v.current_load_kg == 0 for v in s.vehicles.values())


def test_sample_priorities_in_1_to_4():
    s = build_sample_state()
    assert all(1 <= c.priority <= 4 for c in s.customers.values())


def test_sample_graph_nodes_match_entities():
    s = build_sample_state()
    assert "DEPOT" in s.road_graph.nodes
    for cid in s.customers:
        assert cid in s.road_graph.nodes


def test_sample_round_trips():
    s = build_sample_state()
    assert WorldState.from_dict(s.to_dict()).to_dict() == s.to_dict()


def test_sample_has_parallel_edges_depot_to_c001():
    s = build_sample_state()
    parallels = s.road_graph.edges_between("DEPOT", "C001")
    assert len(parallels) == 2
    assert {e.id for e in parallels} == {"DEPOT->C001", "DEPOT->C001#2"}
    # the shortcut floods deeper than a standard truck (wade 0.3 m) can pass
    shortcut = s.road_graph.get_edge("DEPOT->C001#2")
    assert shortcut.is_passable(0.3) is False
    assert shortcut.is_passable(0.6) is True
