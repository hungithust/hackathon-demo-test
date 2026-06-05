"""Default world simulator (M2: living world — demand, inventory, restock, shortage).

Vehicle MOVEMENT is intentionally NOT here: realistic movement needs shortest-path
(M3's matrix), so it lands in M3 with the solver. M2 makes the world *alive* —
demand grows, depot stock is restocked, shortages surface — so the detector and
agent have something real to react to. Fully deterministic given settings.seed."""

import random
from datetime import timedelta

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity,
)


def _seasonal_factor(hour: int) -> float:
    """Hourly demand multiplier: morning + evening peaks, quiet overnight."""
    if 6 <= hour < 10:
        return 1.6
    if 16 <= hour < 20:
        return 1.4
    if 10 <= hour < 16:
        return 1.0
    return 0.4


_BASE_RATE_PER_HOUR = {
    "supermarket": 8.0,
    "market": 12.0,
    "convenience_store": 4.0,
    "restaurant": 6.0,
}
_DEFAULT_BASE_RATE = 5.0


class WorldSimulator:
    def __init__(self, settings):
        self.settings = settings
        self.rng = random.Random(settings.seed)
        self._evt_seq = 0

    def tick(self, state: WorldState) -> None:
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1
        self._generate_demand(state)

    def inject_event(self, state: WorldState, event_type: EventType,
                     target: str, severity: EventSeverity) -> Event:
        evt = Event(
            id=self._new_event_id(), event_type=event_type, target=target,
            severity=severity, started_at=state.clock,
            description=f"injected {event_type.value} on {target}",
        )
        state.events.append(evt)
        return evt

    def _new_event_id(self) -> str:
        self._evt_seq += 1
        return f"EVT_{self._evt_seq:03d}"

    def _sample_units(self, expected: float) -> int:
        """Stochastic rounding: integer demand whose mean equals `expected`."""
        base = int(expected)
        return base + (1 if self.rng.random() < (expected - base) else 0)

    def _generate_demand(self, state: WorldState) -> None:
        if not state.depot.inventory:
            return
        skus = sorted(state.depot.inventory.keys())
        hours_per_tick = self.settings.tick_minutes / 60.0
        factor = _seasonal_factor(state.clock.hour)
        noise = self.settings.demand_noise
        for c in state.customers.values():
            base = _BASE_RATE_PER_HOUR.get(c.type, _DEFAULT_BASE_RATE)
            expected = base * hours_per_tick * factor
            expected *= self.rng.uniform(1.0 - noise, 1.0 + noise)
            units = self._sample_units(expected)
            if units <= 0:
                continue
            sku = self.rng.choice(skus)
            c.orders[sku] = c.orders.get(sku, 0) + units
