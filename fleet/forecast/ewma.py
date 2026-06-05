"""EWMA demand forecaster (M6): single exponential smoothing.

level_0 = history[0]; level_t = alpha*obs_t + (1-alpha)*level_{t-1}. The
horizon-step forecast is flat at the final level (standard for SES). Pure and
deterministic. Prophet plugs in later behind the same Forecaster interface."""

from typing import Dict, List


class EwmaForecaster:
    def __init__(self, settings=None):
        alpha = float(getattr(settings, "ewma_alpha", 0.3) or 0.3)
        # clamp to (0, 1]
        self.alpha = min(1.0, max(1e-6, alpha))

    def forecast(self, history: list, horizon_h: int) -> Dict:
        horizon = max(0, int(horizon_h))
        if not history:
            return {"level": 0.0, "alpha": self.alpha,
                    "forecast": [0.0] * horizon}
        level = float(history[0])
        for obs in history[1:]:
            level = self.alpha * float(obs) + (1.0 - self.alpha) * level
        forecast: List[float] = [level] * horizon
        return {"level": level, "alpha": self.alpha, "forecast": forecast}
