from datetime import datetime, timedelta

from fleet.contracts.state import (
    WorldState, Depot, Location, TimeWindow, CustomerProfile, Vehicle,
    VehicleStatus, RoadGraph, RoadNode, RoadEdge, EdgeStatus,
    Event, EventType, EventSeverity, Decision, DecisionAction, DecisionEngine,
)


def _small_state() -> WorldState:
    t0 = datetime(2026, 6, 4, 6, 0)
    loc_d = Location(10.82, 106.63, "depot addr", "Depot")
    loc_c = Location(10.80, 106.63, "cust addr", "BigC")
    state = WorldState(
        clock=t0,
        depot=Depot(location=loc_d, inventory={"SKU1": 100},
                    opening_time=t0, closing_time=t0 + timedelta(hours=12)),
        customers={"C1": CustomerProfile(
            id="C1", type="supermarket", location=loc_c,
            orders={"SKU1": 10},
            time_window=TimeWindow(t0 + timedelta(hours=1), t0 + timedelta(hours=3)),
            priority=1, sla_deadline=t0 + timedelta(hours=4))},
        vehicles={"V1": Vehicle(id="V1", capacity_kg=500, pos=loc_d,
                                current_load_kg=0, status=VehicleStatus.AT_DEPOT,
                                veh_type="truck", wade_capability=0.3)},
        road_graph=RoadGraph(
            nodes={"DEPOT": RoadNode("DEPOT", loc_d), "C1": RoadNode("C1", loc_c)},
            edges={("DEPOT", "C1"): RoadEdge("DEPOT", "C1", 2.0, 10.0,
                                             status=EdgeStatus.FLOODED, flood_level=0.4)},
            adjacency={"DEPOT": ["C1"]}),
    )
    state.events.append(Event(id="E1", event_type=EventType.TRAFFIC,
                              target="DEPOT->C1", severity=EventSeverity.HIGH,
                              started_at=t0, metrics={"factor": 4.0}))
    state.decisions.append(Decision(
        id="D1", timestamp=t0, event_id="E1", action=DecisionAction.REROUTE,
        engine=DecisionEngine.RULE_BASED, description="reroute around flood",
        impact_estimate={"delay_minutes_saved": 20.0}))
    return state


def test_round_trip_preserves_state():
    state = _small_state()
    snapshot = state.to_dict()
    restored = WorldState.from_dict(snapshot)
    assert restored.to_dict() == snapshot


def test_round_trip_restores_typed_values():
    restored = WorldState.from_dict(_small_state().to_dict())
    assert restored.clock == datetime(2026, 6, 4, 6, 0)
    assert restored.customers["C1"].priority == 1
    edge = restored.road_graph.edges[("DEPOT", "C1")]
    assert edge.status == EdgeStatus.FLOODED
    assert edge.is_passable(0.5) is True
    assert edge.is_passable(0.2) is False
