from datetime import datetime, timedelta

from fleet.contracts.state import (
    WorldState, Depot, Location, CustomerProfile, TimeWindow, Stop, VehicleRoute,
    DecisionAction,
)
from fleet.agent.dataset import realized_delay_minutes, is_informative

_BASE = datetime(2026, 6, 4, 6, 0)


def _depot():
    return Depot(location=Location(0.0, 0.0, "d", "d"), inventory={},
                 opening_time=_BASE, closing_time=_BASE + timedelta(hours=12))


def test_realized_delay_sums_overdue_minutes():
    cust = CustomerProfile(
        id="C1", type="market", location=Location(0.0, 0.0, "c", "c"), orders={},
        time_window=TimeWindow(_BASE, _BASE + timedelta(hours=1)), priority=2)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1, minutes=20))  # 20 min late
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    assert realized_delay_minutes(st) == 20.0


def test_realized_delay_zero_when_on_time():
    cust = CustomerProfile(
        id="C1", type="market", location=Location(0.0, 0.0, "c", "c"), orders={},
        time_window=TimeWindow(_BASE, _BASE + timedelta(hours=2)), priority=2)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1))
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    assert realized_delay_minutes(st) == 0.0


def test_is_informative_uses_cost_gap():
    scored = [(DecisionAction.REPRIORITIZE, 10.0), (DecisionAction.CANCEL, 60.0)]
    assert is_informative(scored, min_gap=1.0) is True
    assert is_informative(scored, min_gap=100.0) is False
    assert is_informative([(DecisionAction.REROUTE, 5.0)], min_gap=1.0) is False
    assert is_informative([], min_gap=1.0) is False
