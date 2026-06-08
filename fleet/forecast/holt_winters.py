"""Holt-Winters (triple exponential smoothing) forecaster with prediction
intervals (M-B). Additive seasonality. Pure, deterministic, stdlib only.

Returns {level, trend, sigma, forecast, lower, upper}. Degrades gracefully:
empty history -> zeros; < 2 full seasons -> flat warm-up forecast (wide
interval) so callers don't trust an under-determined seasonal fit. EWMA stays
the default Forecaster; Holt-Winters is selected via FORECASTER_ENGINE=holt."""

import math
from typing import Dict, List


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _smooth(raw, default: float) -> float:
    """Clamp a smoothing coefficient into (0, 1]."""
    v = float(raw if raw is not None else default)
    return min(1.0, max(1e-6, v))


class HoltWintersForecaster:
    def __init__(self, settings=None):
        self.alpha = _smooth(getattr(settings, "hw_alpha", 0.3), 0.3)
        self.beta = _smooth(getattr(settings, "hw_beta", 0.1), 0.1)
        self.gamma = _smooth(getattr(settings, "hw_gamma", 0.1), 0.1)
        self.m = max(1, int(getattr(settings, "season_length", 24) or 24))
        self.z = float(getattr(settings, "pi_z", 1.96) or 1.96)

    def forecast(self, history: list, horizon_h: int) -> Dict:
        h = max(0, int(horizon_h))
        y = [float(v) for v in history]
        n = len(y)
        if n == 0:
            return {"level": 0.0, "trend": 0.0, "sigma": 0.0,
                    "forecast": [0.0] * h, "lower": [0.0] * h, "upper": [0.0] * h}
        m = self.m
        if n < 2 * m:
            level = _mean(y)
            band = self.z * _std(y)
            return {"level": level, "trend": 0.0, "sigma": _std(y), "warmup": True,
                    "forecast": [level] * h,
                    "lower": [level - band] * h, "upper": [level + band] * h}
        return self._fit(y, n, m, h)

    def _fit(self, y, n, m, h):
        # additive initialization from the first two seasons
        level = _mean(y[:m])
        trend = (_mean(y[m:2 * m]) - _mean(y[:m])) / m
        season = [y[i] - level for i in range(m)]
        residuals: List[float] = []
        for t in range(n):
            s_idx = t % m
            seasonal = season[s_idx]
            if t >= m:                                  # collect one-step residuals
                residuals.append(y[t] - (level + trend + seasonal))
            last_level = level
            level = self.alpha * (y[t] - seasonal) + (1 - self.alpha) * (level + trend)
            trend = self.beta * (level - last_level) + (1 - self.beta) * trend
            season[s_idx] = self.gamma * (y[t] - level) + (1 - self.gamma) * seasonal
        sigma = _std(residuals)
        band = self.z * sigma
        forecast, lower, upper = [], [], []
        for k in range(1, h + 1):
            seasonal = season[(n + k - 1) % m]
            point = level + k * trend + seasonal
            forecast.append(point)
            lower.append(point - band)
            upper.append(point + band)
        return {"level": level, "trend": trend, "sigma": sigma,
                "forecast": forecast, "lower": lower, "upper": upper}
