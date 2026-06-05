from datetime import datetime, timedelta

from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import WorldState, Depot, Location
from config.settings import load_settings


def _minimal_state(inventory):
    t0 = datetime(2026, 6, 5, 8, 0)
    return WorldState(clock=t0,
                      depot=Depot(Location(0, 0, "", "d"), dict(inventory),
                                  t0, t0 + timedelta(hours=12)))


def test_restock_adds_batch_at_interval():
    s = _minimal_state({"SKUX": 100})
    sim = WorldSimulator(load_settings(env={"TICK_MINUTES": "5",
                                            "RESTOCK_INTERVAL_MIN": "10"}))
    sim.tick(s)                       # +5 min: below interval, no restock
    assert s.depot.inventory["SKUX"] == 100
    sim.tick(s)                       # +10 min total: restock adds the batch (100)
    assert s.depot.inventory["SKUX"] == 200


def test_inventory_never_negative():
    s = _minimal_state({"SKUX": 5})
    sim = WorldSimulator(load_settings())
    for _ in range(20):
        sim.tick(s)
    assert all(q >= 0 for q in s.depot.inventory.values())
