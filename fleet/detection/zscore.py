"""Statistical demand-anomaly detector (M6).

Cross-sectional z-score: compares each customer's current total order volume to
the mean/std across all customers (population std). Customers whose z-score meets
settings.zscore_threshold are flagged DEMAND_SURGE. History-free, pure, and
deterministic. Same Detector interface as RuleDetector."""

import math
from typing import List

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity,
)

_HIGH_Z = 3.0


class ZScoreDetector:
    def __init__(self, settings=None):
        self.threshold = float(getattr(settings, "zscore_threshold", 2.0) or 2.0)

    def detect(self, state: WorldState) -> List[Event]:
        totals = {cid: float(sum(c.orders.values()))
                  for cid, c in state.customers.items()}
        n = len(totals)
        if n < 2:
            return []
        mean = sum(totals.values()) / n
        var = sum((v - mean) ** 2 for v in totals.values()) / n
        std = math.sqrt(var)
        if std == 0.0:
            return []
        events: List[Event] = []
        for cid in sorted(totals):                # deterministic order
            z = (totals[cid] - mean) / std
            if z >= self.threshold:
                sev = EventSeverity.HIGH if z >= _HIGH_Z else EventSeverity.MEDIUM
                events.append(Event(
                    id=f"DET_SURGE_{cid}", event_type=EventType.DEMAND_SURGE,
                    target=cid, severity=sev, started_at=state.clock,
                    description=f"demand surge at {cid} (z={z:.2f})",
                    metrics={"z": float(z), "units": totals[cid]}))
        return events
