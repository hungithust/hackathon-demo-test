from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.routing.planner import reroute
from fleet.routing.matrix import build_time_matrix
from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import EdgeStatus, EventType
from config.settings import load_settings


def test_disrupt_edge_changes_graph_and_emits_event():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    evt = sim.disrupt_edge(s, "DEPOT->C001", EdgeStatus.BLOCKED)
    assert s.road_graph.get_edge("DEPOT->C001").status == EdgeStatus.BLOCKED
    assert evt.event_type == EventType.TRAFFIC or evt.event_type == EventType.FLOODED_AREA
    assert evt in s.events


def test_blocking_edge_reroutes_depot_to_c001_via_detour():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    locations = ["DEPOT", "C001", "C002", "C003", "C004"]
    direct = build_time_matrix(s.road_graph, locations, wade_capability=0.3)
    i, j = locations.index("DEPOT"), locations.index("C001")
    before = direct[i][j]

    sim.disrupt_edge(s, "DEPOT->C001", EdgeStatus.BLOCKED)

    after = build_time_matrix(s.road_graph, locations, wade_capability=0.3)
    assert after[i][j] > before     # forced onto a longer detour (or unreachable)


def test_reroute_returns_dropped_list_and_keeps_plan_consistent():
    s = build_sample_state()
    s.customers["C001"].orders = {"SKUX": 20}
    s.depot.inventory["SKUX"] = 200
    comps = build_components(load_settings())
    dropped = reroute(s, comps.optimizer)
    assert isinstance(dropped, list)
    assert s.plan                                   # a fresh plan was written
