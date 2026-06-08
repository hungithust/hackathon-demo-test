"""UI-facing controller (M7). Wraps the headless simulation so a Streamlit (or any)
front end can drive it without touching engine internals: step the world, read a
JSON-friendly snapshot, and approve/reject queued decisions. Reuses run_loop and
reroute so the UI behaves identically to the headless loop."""

from typing import Dict, List, Optional

from fleet.contracts.state import ApprovalStatus
from fleet.scenarios import build_sample_state, build_real_state
from fleet.factory import build_components
from fleet.dispatch.dispatcher import RESOLVE_ACTIONS
from fleet.routing.planner import reroute
from config.settings import load_settings


def _silent(*_args, **_kwargs):
    pass


class SimulationController:
    def __init__(self, state=None, settings=None):
        self.settings = settings or load_settings()
        self.geometry = {}
        if state is not None:
            self.state = state
        elif getattr(self.settings, "world", "sample") == "real":
            self.state = self._load_real_world()
        else:
            self.state = build_sample_state()
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
                offset = (rng.random() - 0.5) * 0.5 * dist
                
                mid_lat = lat1 + dx/2 + ox * offset
                mid_lng = lng1 + dy/2 + oy * offset
                
                q1_lat = lat1 + (mid_lat-lat1)/2 + ox * offset * 0.5
                q1_lng = lng1 + (mid_lng-lng1)/2 + oy * offset * 0.5
                
                q3_lat = mid_lat + (lat2-mid_lat)/2 - ox * offset * 0.5
                q3_lng = mid_lng + (lng2-mid_lng)/2 - oy * offset * 0.5
                
                pts.extend([(q1_lat, q1_lng), (mid_lat, mid_lng), (q3_lat, q3_lng)])
                
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

    def _vehicle_view(self, v) -> Dict:
        route_nodes = self._route_nodes(v.id)
        # next node on the route after the current stop index (clamped)
        nxt = min(max(v.current_stop_index, 0) + 1, len(route_nodes) - 1)
        cap = v.capacity_kg or 1.0
        return {
            "id": v.id, "status": v.status.value,
            "lat": v.pos.lat, "lng": v.pos.lng,
            "stop_index": v.current_stop_index,
            "capacity_kg": v.capacity_kg,
            "load_pct": round(100.0 * v.current_load_kg / cap),
            "route_nodes": route_nodes,
            "leg_to": route_nodes[nxt] if route_nodes else "DEPOT",
        }

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
                 "type": c.type, "orders": sum(c.orders.values())}
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
            reroute(self.state, self.components.optimizer)
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
