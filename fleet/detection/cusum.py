"""CUSUM drift detector (M-C §5.2): catches slow upward regime shifts in demand
that a single-tick threshold misses, by accumulating standardized deviations
above a slack k and alarming when the sum crosses a threshold h. Per customer,
running mean/variance via Welford. Stateful, deterministic (no RNG). Emits a
DEMAND_SURGE event and resets the accumulator after firing."""

import math
from typing import Dict, List

from fleet.contracts.state import WorldState, Event, EventType
from fleet.detection.severity import severity_from_z


class _Running:
    """Welford online mean/variance."""
    __slots__ = ("n", "mean", "m2", "cusum")

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.cusum = 0.0

    def update(self, x: float) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (x - self.mean)

    @property
    def std(self) -> float:
        return math.sqrt(self.m2 / (self.n - 1)) if self.n > 1 else 0.0


class CusumDetector:
    def __init__(self, settings=None):
        self.k = float(getattr(settings, "cusum_k", 0.5) or 0.5)
        self.h = float(getattr(settings, "cusum_threshold", 4.0) or 4.0)
        self.min_history = int(getattr(settings, "detector_min_history", 8) or 8)
        self.stats: Dict[str, _Running] = {}

    def detect(self, state: WorldState) -> List[Event]:
        events: List[Event] = []
        for cid in sorted(state.customers):
            obs = float(sum(state.customers[cid].orders.values()))
            r = self.stats.setdefault(cid, _Running())
            if r.n >= self.min_history and r.std > 1e-9:
                z = (obs - r.mean) / r.std
                r.cusum = max(0.0, r.cusum + z - self.k)
                if r.cusum >= self.h:
                    events.append(Event(
                        id=f"DET_CUSUM_{cid}", event_type=EventType.DEMAND_SURGE,
                        target=cid, severity=severity_from_z(r.cusum),
                        started_at=state.clock,
                        description=f"sustained demand drift at {cid} (cusum {r.cusum:.1f})",
                        metrics={"cusum": float(r.cusum), "mean": float(r.mean)}))
                    r.cusum = 0.0                    # reset after alarm
            r.update(obs)
        return events
