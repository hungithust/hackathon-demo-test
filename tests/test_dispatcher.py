from datetime import datetime

from fleet.contracts.interfaces import Dispatcher as DispatcherProto
from fleet.contracts.state import (
    Decision, DecisionAction, DecisionEngine, Event, EventType, EventSeverity,
    VehicleStatus, VehicleRoute, Stop, PriorityLevel,
)
from fleet.dispatch.dispatcher import Dispatcher
from fleet.scenarios import build_sample_state


def _decision(action, event_id="E1"):
    return Decision(id="D1", timestamp=datetime(2026, 6, 4, 6, 0), event_id=event_id,
                    action=action, engine=DecisionEngine.RULE_BASED, description="x")


def test_conforms_to_protocol():
    assert isinstance(Dispatcher(), DispatcherProto)


def test_apply_marks_executed():
    s = build_sample_state()
    d = Decision(id="D1", timestamp=s.clock, event_id="E1",
                 action=DecisionAction.REROUTE, engine=DecisionEngine.RULE_BASED,
                 description="x")
    Dispatcher().apply(s, d)
    assert d.executed_at == s.clock
    assert d.execution_result == {"status": "applied"}


def test_reprioritize_bumps_target_customer():
    s = build_sample_state()
    s.customers["C003"].priority = 4
    s.events.append(Event(id="E1", event_type=EventType.URGENT_ORDER,
                          target="C003", severity=EventSeverity.HIGH,
                          started_at=s.clock))
    Dispatcher().apply(s, _decision(DecisionAction.REPRIORITIZE))
    assert s.customers["C003"].priority == int(PriorityLevel.P1)


def test_reallocate_retires_broken_vehicle_and_drops_its_route():
    s = build_sample_state()
    s.vehicles["V001"].status = VehicleStatus.BROKEN
    s.plan["V001"] = VehicleRoute(vehicle_id="V001", stops=[
        Stop(customer_id="C001", sequence=1, planned_arrival=s.clock,
             planned_departure=s.clock)])
    s.events.append(Event(id="E1", event_type=EventType.VEHICLE_BREAKDOWN,
                          target="V001", severity=EventSeverity.CRITICAL,
                          started_at=s.clock))
    Dispatcher().apply(s, _decision(DecisionAction.REALLOCATE))
    assert s.vehicles["V001"].status == VehicleStatus.MAINTENANCE
    assert "V001" not in s.plan


def test_defer_drops_stops_for_customers_ordering_the_short_sku():
    s = build_sample_state()
    # C001 orders SKU001; an inventory shortage on SKU001 -> defer C001's stop
    s.events.append(Event(id="E1", event_type=EventType.INVENTORY_SHORTAGE,
                          target="SKU001", severity=EventSeverity.HIGH,
                          started_at=s.clock))
    s.plan["V001"] = VehicleRoute(vehicle_id="V001", stops=[
        Stop(customer_id="C001", sequence=1, planned_arrival=s.clock,
             planned_departure=s.clock)])
    result = None
    d = _decision(DecisionAction.DEFER)
    Dispatcher().apply(s, d)
    assert "C001" in d.execution_result["deferred"]
    assert all(st.customer_id != "C001"
               for r in s.plan.values() for st in r.stops)
