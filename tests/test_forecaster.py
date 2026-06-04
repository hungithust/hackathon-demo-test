from fleet.contracts.interfaces import Forecaster
from fleet.forecast.ewma import EwmaForecaster


def test_conforms_to_protocol():
    assert isinstance(EwmaForecaster(), Forecaster)


def test_forecast_returns_dict():
    out = EwmaForecaster().forecast(history=[], horizon_h=4)
    assert isinstance(out, dict)
