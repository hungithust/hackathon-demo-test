"""Default world simulator. STUB for M1 (clock + event injection only).
M2 adds demand generation, vehicle movement along the matrix, inventory
consumption, and scheduled restock."""

from datetime import timedelta

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity,
)


class WorldSimulator:
    def __init__(self, settings):
        self.settings = settings
        self._evt_seq = 0

    def tick(self, state: WorldState) -> None:
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1

    def inject_event(self, state: WorldState, event_type: EventType,
                     target: str, severity: EventSeverity) -> Event:
        self._evt_seq += 1
        evt = Event(
            id=f"EVT_{self._evt_seq:03d}", event_type=event_type,
            target=target, severity=severity, started_at=state.clock,
            description=f"injected {event_type.value} on {target}",
        )
        state.events.append(evt)
        return evt
