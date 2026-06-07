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
