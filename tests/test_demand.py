from fleet.simulator.engine import WorldSimulator, _seasonal_factor
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def test_demand_accumulates_over_ticks():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    before = s.total_orders_pending()
    for _ in range(10):
        sim.tick(s)
    assert s.total_orders_pending() > before


def test_demand_is_deterministic_for_same_seed():
    s1, s2 = build_sample_state(), build_sample_state()
    sim1 = WorldSimulator(load_settings(env={"SEED": "42"}))
    sim2 = WorldSimulator(load_settings(env={"SEED": "42"}))
    for _ in range(10):
        sim1.tick(s1)
        sim2.tick(s2)
    orders1 = {cid: dict(c.orders) for cid, c in s1.customers.items()}
    orders2 = {cid: dict(c.orders) for cid, c in s2.customers.items()}
    assert orders1 == orders2


def test_seasonal_factor_has_morning_and_evening_peaks():
    assert _seasonal_factor(7) > _seasonal_factor(13)    # morning peak > midday
    assert _seasonal_factor(18) > _seasonal_factor(13)   # evening peak > midday
    assert _seasonal_factor(3) < _seasonal_factor(13)    # night quieter than midday
