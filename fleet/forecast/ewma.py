"""EWMA demand forecaster. STUB for M1 (returns empty forecast).
M6 implements exponential smoothing + hourly seasonality; Prophet plugs in later."""

from typing import Dict


class EwmaForecaster:
    def forecast(self, history: list, horizon_h: int) -> Dict[str, float]:
        return {}
