from datetime import datetime, timedelta

from fleet.contracts.state import (
    PriorityLevel, CustomerProfile, Location, TimeWindow,
    RoadEdge, EdgeStatus, Vehicle, VehicleStatus, Event, EventType,
    EventSeverity, WorldState, Depot,
)


def test_priority_p1_is_most_urgent():
    assert PriorityLevel.P1.value == 1
    assert PriorityLevel.P4.value == 4
    assert PriorityLevel.P1 < PriorityLevel.P4  # IntEnum: 1 < 4


def test_customer_priority_default_is_least_urgent():
    c = CustomerProfile(
        id="C1", type="market",
        location=Location(10.0, 106.0, "addr", "name"),
        orders={"SKU1": 3},
        time_window=TimeWindow(datetime(2026, 6, 4, 8), datetime(2026, 6, 4, 12)),
    )
    assert c.priority == 4


def test_roadedge_effective_time():
    e = RoadEdge("A", "B", distance_km=2, base_time_minutes=10, traffic_factor=2.0)
    assert e.effective_time == 20.0


def test_blocked_edge_forbidden_for_all_vehicles():
    e = RoadEdge("A", "B", 1, 5, status=EdgeStatus.BLOCKED)
    assert e.is_passable(wade_capability=99.0) is False


def test_flood_level_vs_wade_capability():
    e = RoadEdge("A", "B", 1, 5, flood_level=0.4)
    assert e.is_passable(0.5) is True
    assert e.is_passable(0.3) is False


def test_vehicle_has_veh_type_and_wade_capability():
    v = Vehicle(id="V1", capacity_kg=500,
                pos=Location(0, 0, "", "depot"), current_load_kg=0)
    assert isinstance(v.veh_type, str) and v.veh_type
    assert v.wade_capability >= 0


def test_get_active_events_filters_ended():
    now = datetime(2026, 6, 4, 9)
    state = WorldState(
        clock=now,
        depot=Depot(location=Location(0, 0, "", "d"), inventory={},
                    opening_time=now, closing_time=now + timedelta(hours=8)),
    )
    live = Event(id="E1", event_type=EventType.TRAFFIC, target="A->B",
                 severity=EventSeverity.LOW, started_at=now)
    done = Event(id="E2", event_type=EventType.TRAFFIC, target="B->C",
                 severity=EventSeverity.LOW, started_at=now, ended_at=now)
    state.events.extend([live, done])
    active = state.get_active_events()
    assert [e.id for e in active] == ["E1"]


def test_roadedge_id_auto_derives_from_endpoints():
    e = RoadEdge("DEPOT", "C001", 2.0, 10.0)
    assert e.id == "DEPOT->C001"


def test_roadedge_explicit_id_is_preserved():
    e = RoadEdge("DEPOT", "C001", 1.2, 6.0, id="DEPOT->C001#2")
    assert e.id == "DEPOT->C001#2"
