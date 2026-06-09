"""UI-facing controller (M7). Wraps the headless simulation so a Streamlit (or any)
front end can drive it without touching engine internals: step the world, read a
JSON-friendly snapshot, and approve/reject queued decisions. Reuses run_loop and
reroute so the UI behaves identically to the headless loop."""

import math
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from fleet.contracts.state import ApprovalStatus, VehicleStatus
from fleet.scenarios import build_sample_state, build_real_state
from fleet.factory import build_components
from fleet.dispatch.dispatcher import RESOLVE_ACTIONS
from fleet.routing.planner import reroute, plan_total_minutes
from fleet.routing.matrix import shortest_times_from, shortest_path_edges
from config.settings import load_settings


def _silent(*_args, **_kwargs):
    pass


def _interp_polyline(poly: List[Tuple[float, float]], frac: float):
    """Point at `frac` (0..1) of the way along a (lat,lng) polyline, by length."""
    if not poly:
        return None
    if len(poly) == 1 or frac <= 0:
        return poly[0]
    if frac >= 1:
        return poly[-1]
    seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(poly[:-1], poly[1:])]
    total = sum(seg)
    if total <= 0:
        return poly[0]
    target, acc = frac * total, 0.0
    for (a, b), d in zip(zip(poly[:-1], poly[1:]), seg):
        if acc + d >= target:
            t = (target - acc) / d if d > 0 else 0.0
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        acc += d
    return poly[-1]


class SimulationController:
    def __init__(self, state=None, settings=None):
        self.settings = settings or load_settings()
        self.geometry = {}
        if state is not None:
            self.state = state
        elif getattr(self.settings, "world", "sample") == "real":
            self.state = self._load_real_world()
        else:
            self.state = build_sample_state(urban_speed_kmh=self.settings.urban_speed_kmh)
            self.geometry = self._generate_synthetic_geometry(self.state)
        self.components = build_components(self.settings)

    def _generate_synthetic_geometry(self, state):
        import math, random
        geom = {}
        for edge in state.road_graph.edges.values():
            if edge.id in geom: continue
            
            n1 = state.road_graph.nodes[edge.from_node]
            n2 = state.road_graph.nodes[edge.to_node]
            lat1, lng1 = n1.location.lat, n1.location.lng
            lat2, lng2 = n2.location.lat, n2.location.lng
            
            pts = [(lat1, lng1)]
            dx, dy = lat2 - lat1, lng2 - lng1
            dist = math.hypot(dx, dy)
            if dist > 0.001:
                ox, oy = -dy, dx
                # Deterministic random offset per edge
                rng = random.Random(hash(edge.from_node + edge.to_node))
                
                # Create 5-7 intermediate points to make it zigzagged and winding like real roads
                num_pts = rng.randint(5, 7)
                for i in range(1, num_pts):
                    progress = i / num_pts
                    # Vibrate around the straight line, amplitude proportional to dist
                    offset = (rng.random() - 0.5) * 0.8 * dist
                    # Taper off the offset near the ends
                    taper = math.sin(progress * math.pi)
                    
                    p_lat = lat1 + dx * progress + ox * offset * taper
                    p_lng = lng1 + dy * progress + oy * offset * taper
                    pts.append((p_lat, p_lng))
                
            pts.append((lat2, lng2))
            geom[edge.id] = pts
            
            # Reverse edge
            rev_id = f"{edge.to_node}->{edge.from_node}"
            geom[rev_id] = list(reversed(pts))
            
        return geom

    def _load_real_world(self):
        """Build the real-map world, falling back to the sample world (and leaving
        geometry empty) if the OSM graph or osmnx is unavailable."""
        try:
            from fleet.geo.osm_graph import load_drive_graph
            graph = load_drive_graph(self.settings)
            state, geometry = build_real_state(
                graph, urban_speed_kmh=self.settings.urban_speed_kmh)
            self.geometry = geometry
            return state
        except Exception as exc:        # missing graphml / osmnx / bad data
            print(f"[controller] real world unavailable ({exc}); using sample world")
            self.geometry = {}
            return build_sample_state()

    # ----- driving the world -----
    def step(self, n_ticks: int = 1):
        from fleet.loop import run_loop
        run_loop(self.state, self.components, max(1, int(n_ticks)),
                 settings=self.settings, logger=_silent)
        return self

    # ----- view model helpers -----
    def _route_nodes(self, vehicle_id: str) -> List[str]:
        """The vehicle's planned node sequence (DEPOT -> stops -> DEPOT) so the
        control-room map can draw its route. Empty plan -> just the depot."""
        vr = self.state.plan.get(vehicle_id)
        if not vr or not vr.stops:
            return ["DEPOT"]
        stops = sorted(vr.stops, key=lambda st: st.sequence)
        return ["DEPOT"] + [st.customer_id for st in stops] + ["DEPOT"]

    def _next_eta(self, v) -> Optional[str]:
        vr = self.state.plan.get(v.id)
        if not vr or not vr.stops:
            return None
        stops = sorted(vr.stops, key=lambda s: s.sequence)
        nxt = next((s for s in stops if s.actual_arrival is None), None)
        return nxt.planned_arrival.isoformat() if nxt else None

    def _vehicle_view(self, v) -> Dict:
        route_nodes = self._route_nodes(v.id)
        # next node on the route after the current stop index (clamped)
        nxt = min(max(v.current_stop_index, 0) + 1, len(route_nodes) - 1)
        lat, lng = self._vehicle_position(v)
        return {
            "id": v.id, "status": v.status.value,
            "lat": lat, "lng": lng,
            "stop_index": v.current_stop_index,
            "capacity_kg": v.capacity_kg,
            "current_load_kg": v.current_load_kg,
            "load_pct": self._load_pct(v),
            "route_nodes": route_nodes,
            "route_path": self._route_path(v),       # [[lng,lat]...] along real roads
            "leg_to": route_nodes[nxt] if route_nodes else "DEPOT",
            "shift_start": v.shift_start.isoformat() if v.shift_start else None,
            "shift_end": v.shift_end.isoformat() if v.shift_end else None,
            "next_eta": self._next_eta(v),
            "remaining_stops": max(0, len(route_nodes) - 1),
            "veh_type": v.veh_type,
            "fuel_level": v.fuel_level,
        }

    def _load_pct(self, v) -> int:
        """Carried load = goods for stops not yet delivered, as % of capacity. The
        engine never tracks current_load_kg, so derive it from the live plan."""
        cap = v.capacity_kg or 1.0
        vr = self.state.plan.get(v.id)
        if not vr or not vr.stops:
            return 0
        carried = sum(s.demand_kg for s in vr.stops if s.actual_arrival is None)
        return round(100.0 * carried / cap)

    # ----- geometry: drive vehicles along real roads, between ticks -----
    def _node_latlng(self, node: str):
        n = self.state.road_graph.nodes.get(node)
        return (n.location.lat, n.location.lng) if n else None

    def _leg_polyline(self, from_node: str, to_node: str,
                      wade: float) -> List[Tuple[float, float]]:
        """Real (lat,lng) polyline a vehicle drives from from_node to to_node,
        concatenating the shortest-path edge geometries (the leg may pass through
        DEPOT). Falls back to a straight segment when geometry is missing."""
        poly: List[Tuple[float, float]] = []
        for eid in shortest_path_edges(self.state.road_graph, from_node, to_node, wade):
            g = self.geometry.get(eid)
            if not g:
                e = self.state.road_graph.get_edge(eid)
                a, b = self._node_latlng(e.from_node), self._node_latlng(e.to_node)
                g = [a, b] if a and b else []
            for pt in g:
                t = (float(pt[0]), float(pt[1]))
                if not poly or poly[-1] != t:
                    poly.append(t)
        if not poly:
            a, b = self._node_latlng(from_node), self._node_latlng(to_node)
            poly = [a, b] if a and b else []
        return poly

    def _route_path(self, v) -> List[List[float]]:
        """Whole planned route as one [[lng,lat]...] polyline along real roads."""
        route_nodes = self._route_nodes(v.id)
        if len(route_nodes) < 2:
            return []
        wade = float(v.wade_capability)
        out: List[List[float]] = []
        for a, b in zip(route_nodes[:-1], route_nodes[1:]):
            for (lat, lng) in self._leg_polyline(a, b, wade):
                ll = [lng, lat]
                if not out or out[-1] != ll:
                    out.append(ll)
        if out:
            current_pos = self._vehicle_position(v)
            if current_pos is not None:
                current_ll = [current_pos[1], current_pos[0]]
                if out[0] != current_ll:
                    out.insert(0, current_ll)
        return out

    def _vehicle_position(self, v) -> Tuple[float, float]:
        """Interpolate the vehicle along its current leg by sim-time progress, so
        it crawls along the road between ticks instead of teleporting node-to-node."""
        default = (v.pos.lat, v.pos.lng)
        if v.status in (VehicleStatus.BROKEN, VehicleStatus.MAINTENANCE):
            return default
        vr = self.state.plan.get(v.id)
        if not vr or not vr.stops:
            return default
        stops = sorted(vr.stops, key=lambda s: s.sequence)
        nxt = next((s for s in stops if s.actual_arrival is None), None)
        if nxt is None:                                  # route done -> engine pos
            return default
        visited = [s for s in stops if s.actual_arrival is not None]
        from_node = visited[-1].customer_id if visited else "DEPOT"
        to_node = nxt.customer_id
        wade = float(v.wade_capability)
        leg_min = shortest_times_from(self.state.road_graph, from_node, wade).get(to_node)
        if not leg_min or leg_min <= 0:
            return default
        from_time = nxt.planned_arrival - timedelta(minutes=leg_min)
        span = (nxt.planned_arrival - from_time).total_seconds()
        if span <= 0:
            return self._node_latlng(to_node) or default
        frac = max(0.0, min(1.0, (self.state.clock - from_time).total_seconds() / span))
        pt = _interp_polyline(self._leg_polyline(from_node, to_node, wade), frac)
        return pt or default

    # ----- view model -----
    def snapshot(self) -> Dict:
        s = self.state
        by_status = {st: 0 for st in ("pending", "approved", "rejected", "other")}
        for d in s.decisions:
            key = d.approval_status.value
            by_status[key if key in by_status else "other"] += 1
        return {
            "clock": s.clock.isoformat(),
            "sim_tick": s.sim_tick,
            "pending_orders": s.total_orders_pending(),
            "vehicles": [self._vehicle_view(v) for v in s.vehicles.values()],
            "active_events": [
                {"id": e.id, "event_type": e.event_type.value,
                 "target": e.target, "severity": e.severity.value,
                 "started_at": e.started_at.isoformat(),
                 "description": e.description}
                for e in s.get_active_events()
            ],
            "decisions": {
                "total": len(s.decisions),
                "pending": by_status["pending"],
                "approved": by_status["approved"],
                "rejected": by_status["rejected"],
                "other": by_status["other"],
            },
            "pending_decisions": [
                {"id": d.id, "action": d.action.value, "event_id": d.event_id,
                 "description": d.description,
                 "engine": d.engine.value,
                 "timestamp": d.timestamp.isoformat(),
                 "added_delay_min": d.impact_estimate.get("added_delay_min", 0.0)}
                for d in s.get_pending_decisions()
            ],
            # Human-resolved (approved/rejected) decisions, newest first — the
            # "Resolved" tab of the approval queue.
            "resolved": [
                {"id": d.id, "action": d.action.value, "engine": d.engine.value,
                 "status": d.approval_status.value,
                 "added_delay_min": d.impact_estimate.get("added_delay_min", 0.0),
                 "resolved_at": d.approved_at.isoformat() if d.approved_at else None}
                for d in reversed(s.decisions)
                if d.approved_by == "human"
                and d.approval_status.value in ("approved", "rejected")
            ],
            # Decisions the gate auto-applied (small/low-impact) — the "Auto" tab.
            "auto_handled": [
                {"id": d.id, "action": d.action.value, "engine": d.engine.value,
                 "description": d.description,
                 "added_delay_min": d.impact_estimate.get("added_delay_min", 0.0)}
                for d in reversed(s.decisions) if d.approved_by == "auto"
            ],
            "depot": {"lat": s.depot.location.lat, "lng": s.depot.location.lng,
                      "name": s.depot.location.name},
            "customers": [
                {"id": c.id, "lat": c.location.lat, "lng": c.location.lng,
                 "name": c.location.name, "priority": c.priority,
                 "type": c.type,
                 "orders": [{"sku": sku, "qty": qty} for sku, qty in c.orders.items()],
                 "total_qty": sum(c.orders.values()),
                 "time_window": {"start": c.time_window.start.isoformat(),
                                  "end": c.time_window.end.isoformat()},
                 "contact_name": c.contact_name,
                 "contact_phone": c.contact_phone,
                 "notes": c.notes}
                for c in s.customers.values()
            ],
            "routes": [
                {"edge_id": eid, "path": [[lng, lat] for (lat, lng) in poly]}
                for eid, poly in self.geometry.items()
            ],
        }

    # ----- human-in-the-loop approval -----
    def approve(self, decision_id: str):
        d = self._find_pending(decision_id)
        d.approval_status = ApprovalStatus.APPROVED
        d.approved_by = "human"
        d.approved_at = self.state.clock
        self.components.dispatcher.apply(self.state, d)
        if d.action in RESOLVE_ACTIONS and self.state.total_orders_pending() > 0:
            before = plan_total_minutes(self.state)
            reroute(self.state, self.components.optimizer)
            added = max(0.0, plan_total_minutes(self.state) - before)
            d.impact_estimate["added_delay_min"] = round(added, 1)
        return d

    def reject(self, decision_id: str):
        d = self._find_pending(decision_id)
        d.approval_status = ApprovalStatus.REJECTED
        d.approved_by = "human"
        d.approved_at = self.state.clock
        return d

    def _find_pending(self, decision_id: str):
        for d in self.state.get_pending_decisions():
            if d.id == decision_id:
                return d
        raise KeyError(f"no pending decision with id {decision_id!r}")
