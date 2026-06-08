"""Applies an approved decision to the WorldState and records execution.

Each action mutates the world so an approval visibly changes something:
  REROUTE/RESCHEDULE  -> no state mutation here; the caller re-solves routes
                         (the live road graph already excludes blocked edges).
  REPRIORITIZE        -> bump the target customer to top priority (then re-solve).
  REALLOCATE          -> retire the broken vehicle (excluded from the next solve)
                         and drop its undelivered stops so others pick them up.
  DEFER               -> drop the affected customers' stops from the current plan.
  CANCEL              -> drop the target customer's order + stops outright.
  ACCELERATE          -> pull the target customer's time window forward.

`RESOLVE_ACTIONS` tells the caller (loop / UI controller) which actions need a
route re-solve afterwards. DEFER/CANCEL deliberately do NOT re-solve so the
removal sticks for this cycle."""

from typing import List

from fleet.contracts.state import (
    WorldState, Decision, DecisionAction, PriorityLevel,
)

# Actions whose effect is a changed routing problem -> caller should re-solve.
RESOLVE_ACTIONS = frozenset({
    DecisionAction.REROUTE,
    DecisionAction.RESCHEDULE,
    DecisionAction.REPRIORITIZE,
    DecisionAction.REALLOCATE,
})


class Dispatcher:
    def apply(self, state: WorldState, decision: Decision) -> None:
        handler = {
            DecisionAction.REPRIORITIZE: self._reprioritize,
            DecisionAction.REALLOCATE: self._reallocate,
            DecisionAction.DEFER: self._defer,
            DecisionAction.CANCEL: self._cancel,
            DecisionAction.ACCELERATE: self._accelerate,
        }.get(decision.action)
        result = handler(state, decision) if handler else {"status": "applied"}
        decision.executed_at = state.clock
        decision.execution_result = result

    # ----- per-action handlers (return an audit-friendly result dict) -----
    def _reprioritize(self, state: WorldState, decision: Decision) -> dict:
        cust = self._target_customer(state, decision)
        if cust is None:
            return {"status": "noop", "reason": "no target customer"}
        before = cust.priority
        cust.priority = int(PriorityLevel.P1)
        return {"status": "applied", "customer": cust.id,
                "priority": [before, cust.priority]}

    def _reallocate(self, state: WorldState, decision: Decision) -> dict:
        from fleet.contracts.state import VehicleStatus
        ev = self._event(state, decision)
        vehicle = state.get_vehicle(ev.target) if ev is not None else None
        if vehicle is None:                       # fall back to whatever is broken
            vehicle = next((v for v in state.vehicles.values()
                            if v.status == VehicleStatus.BROKEN), None)
        if vehicle is None:
            return {"status": "noop", "reason": "no broken vehicle"}
        vehicle.status = VehicleStatus.MAINTENANCE
        dropped = self._drop_route(state, vehicle.id)
        return {"status": "applied", "vehicle": vehicle.id,
                "dropped_stops": dropped}

    def _defer(self, state: WorldState, decision: Decision) -> dict:
        affected = self._affected_customers(state, decision)
        dropped = self._drop_customer_stops(state, affected)
        return {"status": "applied", "deferred": affected, "dropped_stops": dropped}

    def _cancel(self, state: WorldState, decision: Decision) -> dict:
        cust = self._target_customer(state, decision)
        if cust is None:
            return {"status": "noop", "reason": "no target customer"}
        cust.orders = {}
        dropped = self._drop_customer_stops(state, [cust.id])
        return {"status": "applied", "cancelled": cust.id, "dropped_stops": dropped}

    def _accelerate(self, state: WorldState, decision: Decision) -> dict:
        cust = self._target_customer(state, decision)
        if cust is None:
            return {"status": "noop", "reason": "no target customer"}
        before = {
            "priority": cust.priority,
            "service_time_min": float(getattr(cust, "service_time_min", 10.0)),
        }
        cust.priority = int(PriorityLevel.P1)
        cust.time_window.start = state.clock
        cust.service_time_min = 0.0
        return {"status": "applied", "accelerated": cust.id, "before": before,
                "after": {"priority": cust.priority, "service_time_min": cust.service_time_min}}

    # ----- helpers -----
    def _target_customer(self, state: WorldState, decision: Decision):
        ev = self._event(state, decision)
        if ev is not None and ev.target in state.customers:
            return state.customers[ev.target]
        return None

    def _affected_customers(self, state: WorldState, decision: Decision) -> List[str]:
        ev = self._event(state, decision)
        if ev is None:
            return []
        if ev.target in state.customers:
            return [ev.target]
        # shortage events target a SKU: every customer ordering it is affected.
        sku = ev.target
        return [cid for cid, c in state.customers.items() if sku in c.orders]

    def _event(self, state: WorldState, decision: Decision):
        if decision.event_id is None:
            return None
        return next((e for e in state.events if e.id == decision.event_id), None)

    @staticmethod
    def _drop_customer_stops(state: WorldState, customer_ids: List[str]) -> int:
        targets = set(customer_ids)
        dropped = 0
        for route in state.plan.values():
            kept = [s for s in route.stops if s.customer_id not in targets]
            dropped += len(route.stops) - len(kept)
            route.stops = kept
        return dropped

    @staticmethod
    def _drop_route(state: WorldState, vehicle_id: str) -> int:
        route = state.plan.pop(vehicle_id, None)
        return len(route.stops) if route else 0
