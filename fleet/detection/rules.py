"""Rule-based anomaly detector. STUB for M1 (returns nothing).
M6 adds threshold rules (e.g. traffic_factor >= 4 -> HIGH) and a ZScoreDetector."""

from typing import List

from fleet.contracts.state import WorldState, Event


class RuleDetector:
    def detect(self, state: WorldState) -> List[Event]:
        return []
