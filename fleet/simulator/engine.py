"""Default world simulator (M2: living world — demand, inventory, restock, shortage).

Vehicle MOVEMENT is intentionally NOT here: realistic movement needs shortest-path
(M3's matrix), so it lands in M3 with the solver. M2 makes the world *alive* —
demand grows, depot stock is restocked, shortages surface — so the detector and
agent have something real to react to. Fully deterministic given settings.seed."""

import math
import random
from datetime import timedelta
from typing import Dict

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, VehicleStatus, Vehicle,
    EdgeStatus,
)
from fleet.routing.matrix import shortest_times_from, DEFAULT_SERVICE_TIME_MIN


def _seasonal_factor(hour: int) -> float:
    """Hourly demand multiplier: morning + evening peaks, quiet overnight."""
    if 6 <= hour < 10:
        return 1.6
    if 16 <= hour < 20:
        return 1.4
    if 10 <= hour < 16:
        return 1.0
    return 0.4


def _weekly_factor(weekday: int, weekend_factor: float) -> float:
    """Weekly seasonality: weekends (Sat=5, Sun=6) scaled by weekend_factor."""
    return weekend_factor if weekday >= 5 else 1.0


def _trend_factor(days_elapsed: float, trend_per_day: float) -> float:
    """Slow multiplicative trend over elapsed sim-days, floored at 0."""
    return max(0.0, 1.0 + trend_per_day * days_elapsed)


def _traffic_factor_for_hour(hour: int, peak_factor: float) -> float:
    """Rush-hour congestion multiplier. Peaks (peak_factor) in the morning/evening
    commute, mild at midday, free-flow (1.0) overnight. Caller keeps peak_factor
    below settings.traffic_alert_factor so normal rush hour is not a TRAFFIC alert."""
    if 6 <= hour < 10 or 16 <= hour < 20:
        return peak_factor
    if 10 <= hour < 16:
        return 1.0 + 0.4 * (peak_factor - 1.0)   # ~midday, between free-flow and peak
    return 1.0


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
        self.advance_only = False         # M-F: grading-only mode; tick advances time and movement, but freezes exogenous world updates
        self.rng = random.Random(settings.seed)
        self._evt_seq = 0
        self._mins_since_restock = 0
        self._restock_batch = None      # lazily snapshotted on first tick
        self._ar_state: Dict[str, float] = {}   # M-A: per-customer AR(1) state
        self._regime_until: Dict[str, "datetime"] = {}  # M-A: regime end clock
        self._start_clock = None          # M-A: captured on first tick for trend
        self._weather_rng = random.Random(settings.seed + 1)  # M-A2: independent of demand rng
        self._rain = 0.0                                      # M-A2: rain level in [0,1]
        self._flood_prone = None                              # M-A2: lazily-snapshotted edge ids
        self._weather_flooded: set = set()                    # M-A2: edges flooded BY weather
        self._travel_time_cache: Dict = {}                    # cached shortest-path trees for live travel-time replay

    def tick(self, state: WorldState) -> None:
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1
        if self._restock_batch is None:
            self._restock_batch = dict(state.depot.inventory)
        if self._start_clock is None:
            self._start_clock = state.clock
        if not self.advance_only:
            self._travel_time_cache.clear()
            if self.settings.enable_weather:
                self._step_rain()
                self._update_traffic(state)
                self._update_weather(state)
            self._generate_demand(state)
            self._maybe_restock(state)
            self._update_shortage_events(state)
            self._inject_sudden_events(state)
        self._advance_vehicles(state)

    def _collect_planned_next_edges(self, state: WorldState):
        """Return edges on the 2nd-unvisited leg (vehicle not yet committed) so
        injected jams never land under a vehicle that can't physically escape.
        Direct DEPOT exit edges (from_node==DEPOT) are excluded so disruptions
        appear deep in the network, not on depot access roads."""
        planned = []
        for route in state.plan.values():
            unvisited = sorted([s for s in route.stops if s.actual_arrival is None],
                               key=lambda s: s.sequence)
            if len(unvisited) < 2:
                continue
            # Target the leg vehicle is NOT yet on (1st-unvisited → 2nd-unvisited)
            from_node = unvisited[0].customer_id
            to_node = unvisited[1].customer_id
            for e in state.road_graph.out_edges(from_node):
                if e.to_node == to_node and e.status == EdgeStatus.OPEN:
                    planned.append(e)
                    break
        return planned

    def _flood_area(self, state: WorldState, center_edge, flood_level: float = 0.5,
                    max_extra: int = 4) -> None:
        """Flood the center edge plus up to max_extra neighbouring OPEN edges at its
        endpoints, simulating a flood *zone* rather than a single road segment."""
        nodes_hit = {center_edge.from_node, center_edge.to_node}
        self.disrupt_edge(state, center_edge.id, EdgeStatus.FLOODED, flood_level=flood_level)
        candidates = [
            e for e in state.road_graph.edges.values()
            if e.status == EdgeStatus.OPEN
            and (e.from_node in nodes_hit or e.to_node in nodes_hit)
            and e.id != center_edge.id
        ]
        self.rng.shuffle(candidates)
        for e in candidates[:max_extra]:
            self.disrupt_edge(state, e.id, EdgeStatus.FLOODED, flood_level=flood_level)

    def _inject_sudden_events(self, state: WorldState) -> None:
        """Randomly inject sudden traffic/flood disruptions.

        Traffic jams are preferentially placed on edges vehicles are currently
        heading towards so they reliably trigger reroute decisions in the demo.
        Floods affect a geographic zone (center edge + neighbouring edges)."""
        # Fixed demo jam: DEPOT→C001 congestion injected once at tick 120.
        # The jam covers only the LAST 7/8 of the edge (starts at fraction 0.125)
        # so a vehicle that just left DEPOT can still turn around and reroute.
        if state.sim_tick == 120 and not getattr(self, "_depot_c001_jam_injected", False):
            depot_c001 = state.road_graph.get_edge("DEPOT->C001")
            if depot_c001 and depot_c001.status == EdgeStatus.OPEN:
                # Jam in the last 1/8 of the road (near C001 side).
                # Vehicles that haven't yet traveled 87.5% of the road can still reroute.
                self.disrupt_edge(state, "DEPOT->C001", EdgeStatus.CONGESTED,
                                  traffic_factor=10.0,
                                  congestion_start_frac=0.875,
                                  congestion_end_frac=1.0)
            self._depot_c001_jam_injected = True

        if not any(v.status == VehicleStatus.ON_ROUTE for v in state.vehicles.values()):
            return

        if state.sim_tick < 120:
            return

        if getattr(self, "_last_accident_tick", None) is None:
            self._last_accident_tick = state.sim_tick

        active_traffic = sum(1 for e in state.get_active_events() if e.event_type == EventType.TRAFFIC)
        active_flood = sum(1 for e in state.get_active_events() if e.event_type == EventType.FLOODED_AREA)

        if state.sim_tick - self._last_accident_tick >= 2:
            if self.rng.random() < 0.6:
                # Exclude direct depot exit/entry edges so disruptions appear
                # in the mid-network, not on depot access roads (any depot in
                # multi-depot worlds).
                depot_nodes = set(state.all_depots())
                open_edges = [
                    e for e in state.road_graph.edges.values()
                    if e.status == EdgeStatus.OPEN
                    and e.from_node not in depot_nodes
                    and e.to_node not in depot_nodes
                ]
                if not open_edges:  # fallback when graph has only depot edges
                    open_edges = [e for e in state.road_graph.edges.values()
                                  if e.status == EdgeStatus.OPEN]
                if open_edges:
                    if self.rng.random() < 0.3 and active_flood < 2:
                        center = self.rng.choice(open_edges)
                        self._flood_area(state, center, flood_level=0.5)
                    elif active_traffic < 3:
                        # Prefer the 2nd-leg ahead so no jam lands under a vehicle
                        planned = self._collect_planned_next_edges(state)
                        pool = planned if planned else open_edges
                        edge = self.rng.choice(pool)
                        # Random partial-jam segment: jam covers 1/4 to 3/4 of edge
                        jam_len = self.rng.choice([0.25, 0.375, 0.5, 0.625, 0.75])
                        max_start = 1.0 - jam_len
                        cong_start = round(self.rng.uniform(0.0, max_start), 3)
                        cong_end = round(min(1.0, cong_start + jam_len), 3)
                        self.disrupt_edge(state, edge.id, EdgeStatus.CONGESTED,
                                          traffic_factor=10.0,
                                          congestion_start_frac=cong_start,
                                          congestion_end_frac=cong_end)
            self._last_accident_tick = state.sim_tick

    def inject_event(self, state: WorldState, event_type: EventType,
                     target: str, severity: EventSeverity) -> Event:
        evt = Event(
            id=self._new_event_id(), event_type=event_type, target=target,
            severity=severity, started_at=state.clock,
            description=f"injected {event_type.value} on {target}",
        )
        state.events.append(evt)
        return evt

    def disrupt_edge(self, state: WorldState, edge_id: str,
                     new_status: EdgeStatus, flood_level: float = 0.0,
                     traffic_factor: float = 1.0,
                     congestion_start_frac: float = 0.0,
                     congestion_end_frac: float = 1.0) -> Event:
        """Mutate a road edge (block/flood/congest) and emit the matching event so
        the detector + agent react and the loop's reroute path is exercised.

        congestion_start_frac / congestion_end_frac define the sub-segment of the
        edge that is actually jammed (req 4).  Defaults cover the full edge."""
        edge = state.road_graph.get_edge(edge_id)
        if edge is None:
            raise KeyError(f"no such edge: {edge_id}")
        edge.status = new_status
        self._travel_time_cache.clear()
        if flood_level:
            edge.flood_level = flood_level
        if traffic_factor != 1.0:
            edge.traffic_factor = traffic_factor
        edge.congestion_start_frac = max(0.0, min(1.0, congestion_start_frac))
        edge.congestion_end_frac = max(0.0, min(1.0, congestion_end_frac))
        evt_type = (EventType.FLOODED_AREA
                    if new_status == EdgeStatus.FLOODED
                    else EventType.TRAFFIC)
        if new_status == EdgeStatus.BLOCKED:
            severity = EventSeverity.CRITICAL
        elif new_status == EdgeStatus.FLOODED:
            severity = EventSeverity.HIGH
        elif traffic_factor >= 5.0:
            # Heavy traffic jam: causes delay well above the 30-min SLA threshold.
            severity = EventSeverity.HIGH
        else:
            severity = EventSeverity.MEDIUM
        evt = Event(
            id=self._new_event_id(), event_type=evt_type, target=edge_id,
            severity=severity, started_at=state.clock,
            description=f"{new_status.value} on {edge_id}",
        )
        # We do NOT append to state.events here. The detector will see the edge status
        # and create its own DET_ event to avoid duplicates.
        return evt

    def _new_event_id(self) -> str:
        self._evt_seq += 1
        return f"EVT_{self._evt_seq:03d}"

    def _sample_units(self, expected: float) -> int:
        """Stochastic rounding: integer demand whose mean equals `expected`."""
        base = int(expected)
        return base + (1 if self.rng.random() < (expected - base) else 0)

    def _ar_multiplier(self, cid: str) -> float:
        """AR(1) autocorrelated, mean~1, strictly-positive demand multiplier.

        a_t = rho*a_{t-1} + sqrt(1-rho^2)*eps;  multiplier = exp(sigma*a_t - sigma^2/2).
        The lognormal mean-correction keeps the long-run mean ~= 1.0."""
        rho = self.settings.demand_ar_rho
        sigma = self.settings.demand_ar_sigma
        prev = self._ar_state.get(cid, 0.0)
        eps = self.rng.gauss(0.0, 1.0)
        a = rho * prev + math.sqrt(max(0.0, 1.0 - rho * rho)) * eps
        self._ar_state[cid] = a
        return math.exp(sigma * a - 0.5 * sigma * sigma)

    def _regime_multiplier(self, cid: str, clock) -> float:
        """Occasional promotion regime: with prob `regime_prob` per call a customer
        enters a `regime_factor` demand regime lasting `regime_duration_min`."""
        until = self._regime_until.get(cid)
        if until is not None and clock < until:
            return self.settings.regime_factor
        # not currently in a regime: maybe start one
        if self.rng.random() < self.settings.regime_prob:
            self._regime_until[cid] = clock + timedelta(
                minutes=self.settings.regime_duration_min)
            return self.settings.regime_factor
        return 1.0

    def _step_rain(self) -> float:
        """AR(1) rain process in [0,1]: rho keeps rain spells persistent.
        Uses the independent weather rng so the demand stream is untouched."""
        rho = self.settings.weather_rho
        shock = self._weather_rng.random()
        self._rain = max(0.0, min(1.0, rho * self._rain + (1.0 - rho) * shock))
        return self._rain

    def _update_traffic(self, state: WorldState) -> None:
        """Set rush-hour congestion on OPEN edges only; injected/disrupted edges
        (BLOCKED/FLOODED/CONGESTED) keep their values (§3.2 injection override)."""
        factor = _traffic_factor_for_hour(
            state.clock.hour, self.settings.traffic_peak_factor)
        for edge in state.road_graph.edges.values():
            if edge.status == EdgeStatus.OPEN:
                edge.traffic_factor = factor

    def _update_weather(self, state: WorldState) -> None:
        """Flood-prone edges (those starting flooded / with a baseline flood_level)
        flood when rain >= threshold and recover when it drops. Only edges weather
        itself owns are toggled, so presenter-injected floods elsewhere are safe."""
        if self._flood_prone is None:
            self._flood_prone = {
                eid for eid, e in state.road_graph.edges.items()
                if e.flood_level > 0.0 or e.status == EdgeStatus.FLOODED
            }
        flooding = self._rain >= self.settings.weather_flood_threshold
        for eid in self._flood_prone:
            edge = state.road_graph.get_edge(eid)
            if edge is None:
                continue
            if flooding:
                edge.status = EdgeStatus.FLOODED
                edge.flood_level = self.settings.weather_flood_level
                self._weather_flooded.add(eid)
            elif eid in self._weather_flooded:
                edge.status = EdgeStatus.OPEN
                edge.flood_level = 0.0
                self._weather_flooded.discard(eid)

    def _generate_demand(self, state: WorldState) -> None:
        if not state.depot.inventory:
            return
        skus = sorted(state.depot.inventory.keys())
        hours_per_tick = self.settings.tick_minutes / 60.0
        intraday = _seasonal_factor(state.clock.hour)
        weekly = _weekly_factor(state.clock.weekday(),
                                self.settings.demand_weekend_factor)
        days_elapsed = (
            (state.clock - self._start_clock).total_seconds() / 86400.0
            if self._start_clock is not None else 0.0)
        trend = _trend_factor(days_elapsed, self.settings.demand_trend_per_day)
        for c in state.customers.values():
            base = _BASE_RATE_PER_HOUR.get(c.type, _DEFAULT_BASE_RATE)
            expected = base * hours_per_tick * intraday * weekly * trend
            expected *= self._regime_multiplier(c.id, state.clock)
            expected *= self._ar_multiplier(c.id)
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
        if getattr(self.settings, "enable_travel_time", False):
            self._advance_vehicles_live(state)
            return
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
            # Vehicle has left the depot but hasn't reached its first stop yet
            if vehicle.status == VehicleStatus.AT_DEPOT:
                has_departed = route.start_time and state.clock >= route.start_time
                has_unvisited = any(s.actual_arrival is None for s in route.stops)
                if has_departed and has_unvisited:
                    vehicle.status = VehicleStatus.ON_ROUTE
            all_visited = route.stops and all(
                s.actual_arrival is not None for s in route.stops)
            shift_done = route.end_time is None or state.clock >= route.end_time
            if all_visited and shift_done:
                vehicle.status = VehicleStatus.AT_DEPOT
                vehicle.pos = state.depot_of(vehicle).location
                vehicle.current_stop_index = -1

    def _advance_vehicles_live(self, state: WorldState) -> None:
        """Replay route progress against the current road graph so disruptions
        change realized travel times. No extra simulator state is stored: the
        current node/time are reconstructed from the already-visited stops."""
        for vid, route in state.plan.items():
            vehicle = state.vehicles.get(vid)
            if vehicle is None or vehicle.status in (
                    VehicleStatus.BROKEN, VehicleStatus.MAINTENANCE):
                continue

            visited = [s for s in route.stops if s.actual_arrival is not None]
            visited.sort(key=lambda s: s.sequence)
            if visited:
                last = visited[-1]
                cur_node = last.customer_id
                cur_time = last.actual_departure or (
                    last.actual_arrival + timedelta(minutes=DEFAULT_SERVICE_TIME_MIN))
            else:
                cur_node = vehicle.home_depot
                if route.stops:
                    first_stop = route.stops[0]
                    cache_key = (cur_node, float(vehicle.wade_capability))
                    dist = self._travel_time_cache.get(cache_key)
                    if dist is None:
                        dist = shortest_times_from(state.road_graph, cur_node, vehicle.wade_capability)
                        self._travel_time_cache[cache_key] = dist

                    if first_stop.customer_id in dist:
                        cur_time = first_stop.planned_arrival - timedelta(minutes=dist[first_stop.customer_id])
                    else:
                        cur_time = state.depot_of(vehicle).opening_time
                else:
                    cur_time = state.depot_of(vehicle).opening_time

            for stop in sorted(route.stops, key=lambda s: s.sequence):
                if stop.actual_arrival is not None:
                    continue
                cache_key = (cur_node, float(vehicle.wade_capability))
                dist = self._travel_time_cache.get(cache_key)
                if dist is None:
                    dist = shortest_times_from(
                        state.road_graph, cur_node, vehicle.wade_capability)
                    self._travel_time_cache[cache_key] = dist
                if stop.customer_id not in dist:
                    break
                arrival = cur_time + timedelta(minutes=dist[stop.customer_id])
                if arrival > state.clock:
                    break
                stop.actual_arrival = arrival
                cust = state.customers.get(stop.customer_id)
                service_min = (float(getattr(cust, "service_time_min", DEFAULT_SERVICE_TIME_MIN))
                               if cust is not None else DEFAULT_SERVICE_TIME_MIN)
                stop.actual_departure = arrival + timedelta(minutes=service_min)
                if cust is not None:
                    vehicle.pos = cust.location
                vehicle.current_stop_index = stop.sequence
                vehicle.status = VehicleStatus.ON_ROUTE
                self._deliver(state, vehicle, stop.customer_id)
                cur_node = stop.customer_id
                cur_time = stop.actual_departure

            # Vehicle has left the depot but hasn't reached its first stop yet
            if vehicle.status == VehicleStatus.AT_DEPOT:
                has_departed = route.start_time and state.clock >= route.start_time
                has_unvisited = any(s.actual_arrival is None for s in route.stops)
                if has_departed and has_unvisited:
                    vehicle.status = VehicleStatus.ON_ROUTE
            all_visited = route.stops and all(
                s.actual_arrival is not None for s in route.stops)
            shift_done = route.end_time is None or state.clock >= route.end_time
            if all_visited and shift_done:
                vehicle.status = VehicleStatus.AT_DEPOT
                vehicle.pos = state.depot_of(vehicle).location
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
