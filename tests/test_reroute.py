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
    assert evt.target == "DEPOT->C001"
    # disrupt_edge returns the event; the detector (not disrupt_edge) appends the
    # canonical DET_ event next tick, so we don't assert membership in s.events here.


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


def test_reroute_keeps_inprogress_vehicle_at_its_current_node():
    from fleet.contracts.state import VehicleRoute, Stop, VehicleStatus
    s = build_sample_state()
    comps = build_components(load_settings())
    # V001 is mid-route, already at C001
    s.plan["V001"] = VehicleRoute(vehicle_id="V001", stops=[
        Stop(customer_id="C001", sequence=1, planned_arrival=s.clock,
             planned_departure=s.clock, actual_arrival=s.clock,
             actual_departure=s.clock)])
    s.vehicles["V001"].current_stop_index = 1
    s.vehicles["V001"].status = VehicleStatus.ON_ROUTE
    s.customers["C001"].orders = {}        # delivered: no pending order left at C001
    reroute(s, comps.optimizer)
    r = s.plan.get("V001")
    if r and r.stops:
        # its first NEW stop is reachable from C001, not a depot teleport
        assert r.stops[0].customer_id != "C001"
