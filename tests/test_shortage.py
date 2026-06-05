from datetime import datetime, timedelta

from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import (
    WorldState, Depot, Location, CustomerProfile, TimeWindow, EventType,
)
from config.settings import load_settings

_NO_RESTOCK = {"RESTOCK_INTERVAL_MIN": "100000"}


def _state_with_demand(stock, order_qty):
    t0 = datetime(2026, 6, 5, 8, 0)
    cust = CustomerProfile(
        id="C1", type="market", location=Location(0, 0, "", "c"),
        orders={"SKUX": order_qty},
        time_window=TimeWindow(t0, t0 + timedelta(hours=4)))
    return WorldState(
        clock=t0,
        depot=Depot(Location(0, 0, "", "d"), {"SKUX": stock}, t0,
                    t0 + timedelta(hours=12)),
        customers={"C1": cust})


def _active_shortages(state, sku):
    return [e for e in state.events
            if e.event_type == EventType.INVENTORY_SHORTAGE
            and e.target == sku and e.ended_at is None]


def test_shortage_fires_when_demand_exceeds_stock():
    s = _state_with_demand(stock=0, order_qty=50)
    sim = WorldSimulator(load_settings(env=_NO_RESTOCK))
    sim.tick(s)
    active = _active_shortages(s, "SKUX")
    assert len(active) == 1
    assert active[0].metrics["stock"] == 0.0


def test_shortage_not_duplicated_while_active():
    s = _state_with_demand(stock=0, order_qty=50)
    sim = WorldSimulator(load_settings(env=_NO_RESTOCK))
    sim.tick(s)
    sim.tick(s)
    assert len(_active_shortages(s, "SKUX")) == 1


def test_shortage_resolves_when_stock_recovers():
    s = _state_with_demand(stock=0, order_qty=50)
    sim = WorldSimulator(load_settings(env=_NO_RESTOCK))
    sim.tick(s)
    assert len(_active_shortages(s, "SKUX")) == 1
    s.depot.inventory["SKUX"] = 1_000_000          # stock recovers
    sim.tick(s)
    assert _active_shortages(s, "SKUX") == []
    resolved = [e for e in s.events
                if e.event_type == EventType.INVENTORY_SHORTAGE
                and e.ended_at is not None]
    assert len(resolved) == 1
