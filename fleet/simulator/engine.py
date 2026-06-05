"""Default world simulator (M2: living world — demand, inventory, restock, shortage).

Vehicle MOVEMENT is intentionally NOT here: realistic movement needs shortest-path
(M3's matrix), so it lands in M3 with the solver. M2 makes the world *alive* —
demand grows, depot stock is restocked, shortages surface — so the detector and
agent have something real to react to. Fully deterministic given settings.seed."""

import random
from datetime import timedelta
from typing import Dict

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, VehicleStatus, Vehicle,
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


def _pending_demand_by_sku(state: WorldState) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for c in state.customers.values():
        for sku, qty in c.orders.items():
            out[sku] = out.get(sku, 0) + qty
    return out


class WorldSimulator:
    def __init__(self, settings):
        self.settings = settings
        self.rng = random.Random(settings.seed)
        self._evt_seq = 0
        self._mins_since_restock = 0
        self._restock_batch = None      # lazily snapshotted on first tick

    def tick(self, state: WorldState) -> None:
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1
        if self._restock_batch is None:
            self._restock_batch = dict(state.depot.inventory)
        self._generate_demand(state)
        self._maybe_restock(state)
        self._update_shortage_events(state)
        self._advance_vehicles(state)

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

    def _maybe_restock(self, state: WorldState) -> None:
        self._mins_since_restock += self.settings.tick_minutes
        if self._mins_since_restock < self.settings.restock_interval_min:
            return
        self._mins_since_restock = 0
        for sku, qty in (self._restock_batch or {}).items():
            state.depot.inventory[sku] = state.depot.inventory.get(sku, 0) + qty

    def _update_shortage_events(self, state: WorldState) -> None:
        pending = _pending_demand_by_sku(state)
        active = {e.target: e for e in state.events
                  if e.event_type == EventType.INVENTORY_SHORTAGE
                  and e.ended_at is None}
        for sku, stock in state.depot.inventory.items():
            demand = pending.get(sku, 0)
            if demand > stock:
                if sku not in active:
                    state.events.append(Event(
                        id=self._new_event_id(),
                        event_type=EventType.INVENTORY_SHORTAGE, target=sku,
                        severity=self._shortage_severity(demand, stock),
                        started_at=state.clock,
                        description=f"shortage SKU {sku}: pending {demand} > stock {stock}",
                        metrics={"pending": float(demand), "stock": float(stock)},
                    ))
            elif sku in active:
                active[sku].ended_at = state.clock

    def _advance_vehicles(self, state: WorldState) -> None:
        """Schedule-driven movement: visit every stop whose planned arrival has
        passed, delivering on arrival; return to depot once the shift is over."""
        for vid, route in state.plan.items():
            vehicle = state.vehicles.get(vid)
            if vehicle is None or vehicle.status in (
                    VehicleStatus.BROKEN, VehicleStatus.MAINTENANCE):
                continue
            for stop in route.stops:
                if stop.actual_arrival is None and stop.planned_arrival <= state.clock:
                    stop.actual_arrival = state.clock
                    stop.actual_departure = state.clock
                    cust = state.customers.get(stop.customer_id)
                    if cust is not None:
                        vehicle.pos = cust.location
                    vehicle.current_stop_index = stop.sequence
                    vehicle.status = VehicleStatus.ON_ROUTE
                    self._deliver(state, vehicle, stop.customer_id)
            all_visited = route.stops and all(
                s.actual_arrival is not None for s in route.stops)
            shift_done = route.end_time is None or state.clock >= route.end_time
            if all_visited and shift_done:
                vehicle.status = VehicleStatus.AT_DEPOT
                vehicle.pos = state.depot.location
                vehicle.current_stop_index = -1

    def _deliver(self, state: WorldState, vehicle: "Vehicle",
                 customer_id: str) -> None:
        """Satisfy a customer's outstanding order: draw down depot stock (floored
        at 0) and clear the order."""
        cust = state.customers.get(customer_id)
        if cust is None:
            return
        for sku, qty in cust.orders.items():
            on_hand = state.depot.inventory.get(sku, 0)
            state.depot.inventory[sku] = max(0, on_hand - qty)
        cust.orders = {}

    @staticmethod
    def _shortage_severity(demand: int, stock: int) -> EventSeverity:
        if stock <= 0 or demand >= stock * 2:
            return EventSeverity.CRITICAL
        if demand >= stock * 1.5:
            return EventSeverity.HIGH
        return EventSeverity.MEDIUM
