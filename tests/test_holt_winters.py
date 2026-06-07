from fleet.contracts.interfaces import Forecaster
from fleet.forecast.holt_winters import HoltWintersForecaster
from config.settings import load_settings


def _f(env=None):
    return HoltWintersForecaster(load_settings(env=env or {}))


def test_conforms_to_protocol():
    assert isinstance(HoltWintersForecaster(), Forecaster)


def test_empty_history_is_zero_forecast():
    out = _f().forecast([], horizon_h=3)
    assert out["forecast"] == [0.0, 0.0, 0.0]
    assert out["lower"] == [0.0, 0.0, 0.0]
    assert out["upper"] == [0.0, 0.0, 0.0]


def test_short_history_warms_up_flat_with_interval():
    # season_length=3 needs >=6 points; give 4 -> warm-up flat mean
    out = _f({"SEASON_LENGTH": "3"}).forecast([10.0, 12.0, 8.0, 10.0], horizon_h=2)
    assert out.get("warmup") is True
    assert out["forecast"] == [10.0, 10.0]            # flat at the mean
    assert out["lower"][0] <= out["forecast"][0] <= out["upper"][0]


def test_nonpositive_horizon_returns_empty_forecast():
    out = _f().forecast([1.0, 2.0, 3.0], horizon_h=0)
    assert out["forecast"] == []


def test_trend_series_forecasts_upward():
    # strictly increasing series, season_length small -> forecast keeps rising
    hist = [float(i) for i in range(24)]      # 0,1,2,...,23
    out = _f({"SEASON_LENGTH": "4"}).forecast(hist, horizon_h=4)
    assert out["trend"] > 0
    assert out["forecast"][-1] > out["forecast"][0]
    assert out["forecast"][0] > hist[-1] - 5    # continues near the last value, not flat


def test_seasonal_pattern_is_reproduced():
    # repeating season [2, 10, 4] over 6 cycles; m=3
    base = [2.0, 10.0, 4.0]
    hist = base * 6
    out = _f({"SEASON_LENGTH": "3"}).forecast(hist, horizon_h=3)
    fc = out["forecast"]
    # the next step continues the cycle: peak (10) should be the largest of the 3
    assert max(fc) == fc[1]
    assert fc[1] > fc[0] and fc[1] > fc[2]
