from fleet.contracts.interfaces import Forecaster
from fleet.forecast.ewma import EwmaForecaster
from config.settings import load_settings


def test_conforms_to_protocol():
    assert isinstance(EwmaForecaster(), Forecaster)


def test_forecast_returns_dict():
    out = EwmaForecaster().forecast(history=[], horizon_h=4)
    assert isinstance(out, dict)


def test_constant_series_forecasts_constant():
    f = EwmaForecaster(load_settings(env={"EWMA_ALPHA": "0.5"}))
    out = f.forecast([10.0, 10.0, 10.0], horizon_h=3)
    assert out["level"] == 10.0
    assert out["alpha"] == 0.5
    assert out["forecast"] == [10.0, 10.0, 10.0]


def test_smoothing_recurrence_matches_hand_calc():
    # level0=0; +0.5*(10-0)=5; +0.5*(20-5)=12.5
    f = EwmaForecaster(load_settings(env={"EWMA_ALPHA": "0.5"}))
    out = f.forecast([0.0, 10.0, 20.0], horizon_h=2)
    assert out["level"] == 12.5
    assert out["forecast"] == [12.5, 12.5]


def test_empty_history_is_zero_forecast():
    f = EwmaForecaster(load_settings())
    out = f.forecast([], horizon_h=3)
    assert out["level"] == 0.0
    assert out["forecast"] == [0.0, 0.0, 0.0]


def test_nonpositive_horizon_returns_empty_forecast():
    f = EwmaForecaster(load_settings())
    out = f.forecast([1.0, 2.0], horizon_h=0)
    assert out["forecast"] == []


def test_default_alpha_when_no_settings():
    f = EwmaForecaster()           # settings optional
    out = f.forecast([5.0], horizon_h=1)
    assert out["alpha"] == 0.3
    assert out["forecast"] == [5.0]
