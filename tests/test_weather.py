from datetime import timedelta

from fleet.contracts.state import EdgeStatus
from fleet.simulator.engine import WorldSimulator, _traffic_factor_for_hour
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def test_traffic_peaks_at_rush_hours_and_stays_below_alert():
    peak = 1.8
    alert = 3.0
    assert _traffic_factor_for_hour(8, peak) == peak        # morning rush
    assert _traffic_factor_for_hour(18, peak) == peak       # evening rush
    assert _traffic_factor_for_hour(13, peak) < peak        # midday lighter
    assert _traffic_factor_for_hour(3, peak) == 1.0         # night = free flow
    assert _traffic_factor_for_hour(8, peak) < alert        # never a false TRAFFIC alert


def test_rain_is_bounded_autocorrelated_and_deterministic():
    s1 = WorldSimulator(load_settings(env={"SEED": "5", "WEATHER_RHO": "0.9"}))
    s2 = WorldSimulator(load_settings(env={"SEED": "5", "WEATHER_RHO": "0.9"}))
    xs = [s1._step_rain() for _ in range(300)]
    ys = [s2._step_rain() for _ in range(300)]
    assert xs == ys                              # same seed => identical
    assert all(0.0 <= r <= 1.0 for r in xs)      # rain level normalized to [0,1]
    a, b = xs[:-1], xs[1:]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    assert cov / (va * vb) > 0.4                  # rho=0.9 => persistent rain spells


def test_weather_rng_is_independent_of_demand_rng():
    # Stepping rain must not consume the demand rng (so M-A determinism is unaffected).
    sim = WorldSimulator(load_settings(env={"SEED": "42"}))
    before = sim.rng.random()
    sim2 = WorldSimulator(load_settings(env={"SEED": "42"}))
    sim2._step_rain(); sim2._step_rain(); sim2._step_rain()
    after = sim2.rng.random()
    assert before == after        # demand rng stream unchanged by rain steps
