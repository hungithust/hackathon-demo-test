from datetime import datetime, timedelta

from config.settings import load_settings
from fleet.scenarios import build_sample_state
from fleet.simulator.engine import _weekly_factor, _trend_factor, WorldSimulator


def test_weekly_factor_weekend_lower_than_weekday():
    # 2026-06-08 is a Monday; 2026-06-13 is a Saturday
    monday = datetime(2026, 6, 8)
    saturday = datetime(2026, 6, 13)
    assert _weekly_factor(monday.weekday(), 0.7) == 1.0
    assert _weekly_factor(saturday.weekday(), 0.7) == 0.7
    assert _weekly_factor(monday.weekday(), 0.7) > _weekly_factor(saturday.weekday(), 0.7)


def test_trend_factor_grows_with_days():
    assert _trend_factor(0.0, 0.05) == 1.0
    assert _trend_factor(2.0, 0.05) == 1.1       # 1 + 0.05*2
    assert _trend_factor(10.0, 0.05) > _trend_factor(1.0, 0.05)


def test_trend_factor_never_negative():
    assert _trend_factor(100.0, -0.05) == 0.0    # clamped at 0, not negative


def _ar_series(sim, cid, n):
    # underlying AR state is what we test for autocorrelation
    out = []
    for _ in range(n):
        sim._ar_multiplier(cid)
        out.append(sim._ar_state[cid])
    return out


def test_ar_noise_is_positively_autocorrelated():
    sim = WorldSimulator(load_settings(env={"DEMAND_AR_RHO": "0.9", "SEED": "7"}))
    xs = _ar_series(sim, "C1", 400)
    a = xs[:-1]
    b = xs[1:]
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    corr = cov / (va * vb)
    assert corr > 0.5            # rho=0.9 => strongly positively autocorrelated


def test_ar_multiplier_is_positive_and_deterministic():
    s1 = WorldSimulator(load_settings(env={"SEED": "42"}))
    s2 = WorldSimulator(load_settings(env={"SEED": "42"}))
    seq1 = [s1._ar_multiplier("C1") for _ in range(20)]
    seq2 = [s2._ar_multiplier("C1") for _ in range(20)]
    assert seq1 == seq2                 # same seed => identical
    assert all(m > 0 for m in seq1)     # multiplier always positive


def test_regime_starts_when_prob_one():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"REGIME_PROB": "1.0", "REGIME_FACTOR": "2.0"}))
    m = sim._regime_multiplier("C1", s.clock)
    assert m == 2.0                       # forced into regime => factor applied


def test_no_regime_when_prob_zero():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"REGIME_PROB": "0.0"}))
    assert sim._regime_multiplier("C1", s.clock) == 1.0


def test_regime_is_deterministic():
    s = build_sample_state()
    s1 = WorldSimulator(load_settings(env={"SEED": "42", "REGIME_PROB": "0.3"}))
    s2 = WorldSimulator(load_settings(env={"SEED": "42", "REGIME_PROB": "0.3"}))
    clk = s.clock
    seq1, seq2 = [], []
    for _ in range(30):
        seq1.append(s1._regime_multiplier("C1", clk))
        seq2.append(s2._regime_multiplier("C1", clk))
        clk += timedelta(minutes=30)
    assert seq1 == seq2
