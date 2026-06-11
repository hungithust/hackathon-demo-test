"""Forecast-residual demand detector (M-C §5.1): per customer, forecast the next
order volume from the customer's own history (via an injected interval-producing
Forecaster, e.g. Holt-Winters) and flag DEMAND_SURGE when the actual exceeds the
upper prediction band. Dynamic, context-aware threshold — the band is wide at
rush hour, narrow overnight. Stateful (keeps per-customer history); deterministic
(no RNG). Pairs with the kept RuleDetector via CompositeDetector."""

from typing import Dict, List

from fleet.contracts.state import WorldState, Event, EventType
from fleet.detection.severity import severity_from_z

_MAX_HISTORY = 240          # ring-buffer cap per customer


class ForecastResidualDetector:
    def __init__(self, settings=None, forecaster=None):
        if forecaster is None:                       # lazy default avoids import cycle at module top
            from fleet.forecast.holt_winters import HoltWintersForecaster
            forecaster = HoltWintersForecaster(settings)
        self.forecaster = forecaster
        self.min_history = int(getattr(settings, "detector_min_history", 8) or 8)
        self.history: Dict[str, List[float]] = {}

    def detect(self, state: WorldState) -> List[Event]:
        events: List[Event] = []
        for cid in sorted(state.customers):
            obs = float(sum(state.customers[cid].orders.values()))
            hist = self.history.setdefault(cid, [])
            if len(hist) >= self.min_history:
                out = self.forecaster.forecast(hist, 1)
                upper = out["upper"][0]
                if not out.get("warmup") and obs > upper:
                    point = out["forecast"][0]
                    sigma = out.get("sigma", 0.0)
                    z = (obs - point) / sigma if sigma > 1e-9 else 4.0
                    events.append(Event(
                        id=f"DET_RESID_{cid}", event_type=EventType.DEMAND_SURGE,
                        target=cid, severity=severity_from_z(z),
                        started_at=state.clock,
                        description=f"demand {obs:.0f} above forecast band {upper:.1f} at {cid}",
                        metrics={"actual": obs, "upper": float(upper), "z": float(z)}))
            hist.append(obs)
            if len(hist) > _MAX_HISTORY:
                del hist[0]
        return events
