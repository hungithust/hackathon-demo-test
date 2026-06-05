from datetime import datetime

from fleet.detection.rules import RuleDetector
from fleet.contracts.state import (
    WorldState, Depot, Location, RoadGraph, RoadEdge, RoadNode,
    Vehicle, VehicleStatus, EdgeStatus, EventType, EventSeverity,
)
from config.settings import load_settings


def _bare_state():
    depot = Depot(location=Location(0.0, 0.0, "", ""), inventory={},
                  opening_time=datetime(2026, 6, 4, 6, 0),
                  closing_time=datetime(2026, 6, 4, 18, 0))
    return WorldState(clock=datetime(2026, 6, 4, 7, 0), depot=depot)


def _put_edge(state, edge):
    state.road_graph.nodes.setdefault(
        edge.from_node, RoadNode(id=edge.from_node, location=Location(0.0, 0.0, "", "")))
    state.road_graph.edges[edge.id] = edge
    state.road_graph.adjacency.setdefault(edge.from_node, []).append(edge.id)


def test_blocked_edge_is_critical_traffic():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0, status=EdgeStatus.BLOCKED))
    events = RuleDetector(load_settings()).detect(s)
    e = next(ev for ev in events if ev.target == "A->B")
    assert e.event_type == EventType.TRAFFIC
    assert e.severity == EventSeverity.CRITICAL


def test_flooded_edge_severity_scales_with_depth():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0,
                          status=EdgeStatus.FLOODED, flood_level=0.6))
    e = RuleDetector(load_settings()).detect(s)[0]
    assert e.event_type == EventType.FLOODED_AREA
    assert e.severity == EventSeverity.HIGH


def test_high_traffic_factor_emits_traffic():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0, traffic_factor=3.5))
    e = RuleDetector(load_settings(env={"TRAFFIC_ALERT_FACTOR": "3"})).detect(s)[0]
    assert e.event_type == EventType.TRAFFIC
    assert e.severity == EventSeverity.MEDIUM     # 3.5 < 2*3


def test_normal_edge_emits_nothing():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0, traffic_factor=1.0))
    assert RuleDetector(load_settings()).detect(s) == []


def test_broken_vehicle_is_breakdown_event():
    s = _bare_state()
    s.vehicles["V001"] = Vehicle(id="V001", capacity_kg=500,
                                 pos=Location(0.0, 0.0, "", ""), current_load_kg=0.0,
                                 status=VehicleStatus.BROKEN)
    e = RuleDetector(load_settings()).detect(s)[0]
    assert e.event_type == EventType.VEHICLE_BREAKDOWN
    assert e.target == "V001"
    assert e.severity == EventSeverity.CRITICAL


def test_deterministic_ids_no_duplicates():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0, status=EdgeStatus.BLOCKED))
    ev1 = RuleDetector(load_settings()).detect(s)
    ev2 = RuleDetector(load_settings()).detect(s)
    assert [e.id for e in ev1] == [e.id for e in ev2]   # stable across calls
    assert len({e.id for e in ev1}) == len(ev1)         # unique within a call


from fleet.detection.zscore import ZScoreDetector
from fleet.contracts.state import CustomerProfile, TimeWindow


def _add_customer(state, cid, units):
    state.customers[cid] = CustomerProfile(
        id=cid, type="market", location=Location(0.0, 0.0, "", ""),
        orders={"SKUX": units},
        time_window=TimeWindow(state.depot.opening_time,
                               state.depot.closing_time))


def test_outlier_customer_flagged_as_demand_surge():
    s = _bare_state()
    # enough baseline customers that the outlier's population-std z-score >= 3
    for i in range(10):
        _add_customer(s, f"C{i:03d}", 10)
    _add_customer(s, "C999", 200)        # extreme outlier
    events = ZScoreDetector(load_settings()).detect(s)
    targets = {e.target for e in events}
    assert "C999" in targets
    e = next(ev for ev in events if ev.target == "C999")
    assert e.event_type == EventType.DEMAND_SURGE
    assert e.severity == EventSeverity.HIGH       # z well above 3
    assert e.metrics["units"] == 200.0


def test_uniform_demand_emits_nothing():
    s = _bare_state()
    for cid in ("C001", "C002", "C003"):
        _add_customer(s, cid, 10)
    assert ZScoreDetector(load_settings()).detect(s) == []


def test_fewer_than_two_customers_emits_nothing():
    s = _bare_state()
    _add_customer(s, "C001", 50)
    assert ZScoreDetector(load_settings()).detect(s) == []


def test_threshold_is_configurable():
    s = _bare_state()
    for cid, u in (("C001", 10), ("C002", 10), ("C003", 10), ("C004", 22)):
        _add_customer(s, cid, u)
    # with a high cutoff, the mild outlier is ignored
    assert ZScoreDetector(load_settings(env={"ZSCORE_THRESHOLD": "5"})).detect(s) == []
    # with a low cutoff, it is flagged
    flagged = ZScoreDetector(load_settings(env={"ZSCORE_THRESHOLD": "1.2"})).detect(s)
    assert any(e.target == "C004" for e in flagged)
