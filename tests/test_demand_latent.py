from datetime import datetime

from fleet.simulator.engine import _weekly_factor, _trend_factor


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
