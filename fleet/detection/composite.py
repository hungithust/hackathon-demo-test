"""CompositeDetector (M-C §5): run several Detectors and concatenate their events,
so the deterministic RuleDetector (ground-truth) and the statistical detectors
(forecast-residual, CUSUM) layer cleanly behind the single Detector interface.
The loop's DET_* lifecycle + dedup handle repeats."""

from typing import List

from fleet.contracts.state import WorldState, Event


class CompositeDetector:
    def __init__(self, detectors: list):
        self.detectors = list(detectors)

    def detect(self, state: WorldState) -> List[Event]:
        events: List[Event] = []
        for d in self.detectors:
            events.extend(d.detect(state))
        return events
