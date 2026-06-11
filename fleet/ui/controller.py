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
        # Keyed by vehicle_id; set when a vehicle must return to DEPOT after reroute
        self._return_context: Dict = {}
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
            "load_pct": self._load_pct(v),
            "route_nodes": route_nodes,
            "route_path": self._route_path(v),       # [[lng,lat]...] along real roads
            "return_path": self._return_path(v),     # [[lng,lat]...] dashed return-to-depot leg
            "leg_to": route_nodes[nxt] if route_nodes else "DEPOT",
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

    def _leg_polyline(self, u: str, v: str, wade: float, use_base: bool = False) -> List[Tuple[float, float]]:
        """Real (lat,lng) polyline a vehicle drives from u to v,
        concatenating the shortest-path edge geometries (the leg may pass through
        DEPOT). Falls back to a straight segment when geometry is missing."""
        poly: List[Tuple[float, float]] = []
        for eid in shortest_path_edges(self.state.road_graph, u, v, wade, use_base=use_base):
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
            a, b = self._node_latlng(u), self._node_latlng(v)
            if a and b:
                return [a, b]
        return poly

    def _truncate_polyline(self, poly: List[Tuple[float, float]], frac: float) -> List[List[float]]:
        """Return the 0..frac prefix of a (lat,lng) polyline as [[lng,lat]...] for the UI."""
        if not poly or frac <= 0:
            return []
        if frac >= 1:
            return [[p[1], p[0]] for p in poly]
        segs = [math.hypot(poly[i+1][0]-poly[i][0], poly[i+1][1]-poly[i][1])
                for i in range(len(poly)-1)]
        total = sum(segs)
        if total <= 0:
            return [[poly[0][1], poly[0][0]]]
        target, acc = frac * total, 0.0
        result = [[poly[0][1], poly[0][0]]]
        for i, seg in enumerate(segs):
            if acc + seg >= target:
                t = (target - acc) / seg if seg > 0 else 0.0
                lat = poly[i][0] + (poly[i+1][0] - poly[i][0]) * t
                lng = poly[i][1] + (poly[i+1][1] - poly[i][1]) * t
                result.append([lng, lat])
                break
            acc += seg
            result.append([poly[i+1][1], poly[i+1][0]])
        return result

    def _return_path(self, v) -> Optional[List]:
        """Dashed return path: DEPOT → vehicle's departure position along the original
        edge. Shown while the vehicle is animating back to DEPOT after a reroute."""
        ctx = self._return_context.get(v.id)
        if not ctx:
            return None
        elapsed_min = (self.state.clock - ctx['approval_clock']).total_seconds() / 60.0
        if elapsed_min >= ctx['return_duration_min']:
            return None
        wade = float(v.wade_capability)
        poly = self._leg_polyline(ctx['from_node'], ctx['to_node'], wade, use_base=True)
        return self._truncate_polyline(poly, ctx['frac_at_approval'])

    def _has_pending_reroute(self, vehicle_id: str) -> bool:
        """True if there is a pending reroute/reschedule decision that includes
        this vehicle in its proposed_routes — used to decide which path to render."""
        from fleet.contracts.state import DecisionAction
        for d in self.state.get_pending_decisions():
            if d.action in (DecisionAction.REROUTE, DecisionAction.RESCHEDULE):
                if d.execution_result:
                    if vehicle_id in d.execution_result.get("proposed_routes", {}):
                        return True
        return False

    def _route_path(self, v) -> List[List[float]]:
        """Whole planned route as one [[lng,lat]...] polyline along real roads.

        While a reroute decision is pending: use base_time (ignores disruptions)
        so the blue route stays on its original path through the affected area,
        contrasting visibly with the green proposed-reroute overlay.

        After approval (no pending decision): switch to effective_time so the
        blue route follows the newly approved detour around the disruption."""
        route_nodes = self._route_nodes(v.id)
        if len(route_nodes) < 2:
            return []
        wade = float(v.wade_capability)
        use_base = self._has_pending_reroute(v.id)
        out: List[List[float]] = []
        for a, b in zip(route_nodes[:-1], route_nodes[1:]):
            for (lat, lng) in self._leg_polyline(a, b, wade, use_base=use_base):
                ll = [lng, lat]
                if not out or out[-1] != ll:
                    out.append(ll)
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

        # Return-to-DEPOT animation: vehicle was rerouted and must drive back first
        ctx = self._return_context.get(v.id)
        if ctx:
            elapsed_min = (self.state.clock - ctx['approval_clock']).total_seconds() / 60.0
            if elapsed_min < ctx['return_duration_min']:
                progress = elapsed_min / max(0.001, ctx['return_duration_min'])
                cur_frac = ctx['frac_at_approval'] * (1.0 - progress)
                wade = float(v.wade_capability)
                pt = _interp_polyline(
                    self._leg_polyline(ctx['from_node'], ctx['to_node'], wade, use_base=True),
                    cur_frac)
                return pt or default
            else:
                self._return_context.pop(v.id, None)

        # Draw the moving icon along the SAME path geometry as the vehicle's route
        # line (_route_path): base-time (ignores disruptions) only while a reroute
        # is still pending, effective-time (passable, avoids floods/blocks) once it
        # is approved. Hardcoding use_base=True here made the icon cut straight
        # through a flooded/blocked area even after its route was rerouted around it.
        use_base = self._has_pending_reroute(v.id)

        stops = sorted(vr.stops, key=lambda s: s.sequence)
        nxt = next((s for s in stops if s.actual_arrival is None), None)
        visited = [s for s in stops if s.actual_arrival is not None]

        if nxt is None:
            # Route done (all stops visited). Is it back at depot?
            if v.pos == self.state.depot.location:
                return default
            # It is currently driving back to the depot
            from_node = visited[-1].customer_id if visited else "DEPOT"
            to_node = "DEPOT"
            from_time = visited[-1].actual_departure if visited else self.state.depot.opening_time
            if from_time is None:
                # Still doing service at the last customer
                return default
            wade = float(v.wade_capability)
            leg_min = shortest_times_from(self.state.road_graph, from_node, wade).get(to_node)
            if not leg_min or leg_min <= 0:
                return default
            span = leg_min * 60.0
            frac = max(0.0, min(1.0, (self.state.clock - from_time).total_seconds() / span))
            pt = _interp_polyline(self._leg_polyline(from_node, to_node, wade, use_base=use_base), frac)
            return pt or default

        # Otherwise, en route to `nxt`
        from_node = visited[-1].customer_id if visited else "DEPOT"
        to_node = nxt.customer_id
        wade = float(v.wade_capability)
        # Use effective leg time for span: when a traffic jam raises effective_time
        # 10× the vehicle visually crawls along the road at 1/10th speed.
        eff_leg_min = max(1.0, shortest_times_from(
            self.state.road_graph, from_node, wade).get(to_node, 1.0))
        if visited and visited[-1].actual_departure:
            from_time = visited[-1].actual_departure
        elif not visited and vr.start_time and self.state.clock >= vr.start_time:
            from_time = vr.start_time
        else:
            from_time = nxt.planned_arrival - timedelta(minutes=eff_leg_min)
        span = eff_leg_min * 60.0
        frac = max(0.0, min(1.0, (self.state.clock - from_time).total_seconds() / span))
        pt = _interp_polyline(self._leg_polyline(from_node, to_node, wade, use_base=use_base), frac)
        return pt or default

    def _active_edge_ids(self) -> set:
        """Always return every edge so the full road network stays visible
        throughout the simulation (routes, bypasses, floods, junctions all shown)."""
        return set(self.geometry.keys())

    def _build_proposed_paths(self, proposed_routes):
        if not proposed_routes: return None
        out = {}
        for vid, nodes in proposed_routes.items():
            if len(nodes) < 2: continue
            v = self.state.get_vehicle(vid)
            wade = float(v.wade_capability) if v else 0.3
            path = []
            for a, b in zip(nodes[:-1], nodes[1:]):
                for (lat, lng) in self._leg_polyline(a, b, wade, use_base=False):
                    ll = [lng, lat]
                    if not path or path[-1] != ll:
                        path.append(ll)
            out[vid] = path
        return out

    # ----- view model -----
    def snapshot(self) -> Dict:
        s = self.state
        by_status = {st: 0 for st in ("pending", "approved", "rejected", "other")}
        for d in s.decisions:
            key = d.approval_status.value
            by_status[key if key in by_status else "other"] += 1
        active_eids = self._active_edge_ids()
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
                 "added_delay_min": d.impact_estimate.get("added_delay_min", 0.0),
                 "proposed_routes": d.execution_result.get("proposed_routes") if d.execution_result else None,
                 "proposed_paths": self._build_proposed_paths(d.execution_result.get("proposed_routes")) if d.execution_result else None}
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
                 "type": c.type, "orders": sum(c.orders.values()),
                 # True once any vehicle has actually visited (actual_arrival set).
                 # Persists even after demand_generation refills c.orders.
                 "delivered": any(
                     s.customer_id == c.id and s.actual_arrival is not None
                     for vr in s.plan.values() for s in vr.stops)}
                for c in s.customers.values()
            ],
            "routes": [
                {"edge_id": eid, "path": [[lng, lat] for (lat, lng) in poly]}
                for eid, poly in self.geometry.items()
                if eid in active_eids
            ],
        }

    # ----- human-in-the-loop approval -----
    def _handle_sibling_decisions(self, primary_d, status):
        """Auto-resolve any other pending REROUTE decision on the SAME physical road
        so the user doesn't have to click twice for a bidirectional / parallel-edge
        disruption (loop.py now dedups these, but resolve any that slipped through:
        e.g. queued before the dedup, or forward+reverse of one corridor)."""
        from fleet.contracts.state import DecisionAction
        from fleet.loop import road_key
        if primary_d.action != DecisionAction.REROUTE:
            return
        ev = next((e for e in self.state.events if e.id == primary_d.event_id), None)
        if not ev or "->" not in ev.target:
            return
        key = road_key(ev.target)
        for other_d in self.state.get_pending_decisions():
            if other_d.id == primary_d.id or other_d.action != DecisionAction.REROUTE:
                continue
            o_ev = next((e for e in self.state.events if e.id == other_d.event_id), None)
            if o_ev and "->" in o_ev.target and road_key(o_ev.target) == key:
                other_d.approval_status = status
                other_d.approved_by = "auto-sibling"
                other_d.approved_at = self.state.clock

    def approve(self, decision_id: str):
        d = self._find_pending(decision_id)

        # Re-solve the targeted reroute from each affected vehicle's CURRENT
        # position.  The plan stored when the decision was queued
        # (_proposed_plan) is stale: the vehicle keeps moving (and may visit more
        # stops) while the decision waits in the approval queue, so applying that
        # snapshot would rewind the vehicle's progress and send it back along the
        # old route — it appears to ignore the reroute entirely.  Recomputing here
        # reflects where the vehicle actually is now (and correctly skips a vehicle
        # that has since entered the jam).  The stale snapshot is kept only as a
        # fallback and still drives the green preview while the decision is pending.
        from fleet.contracts.state import DecisionAction
        proposed_plan = None
        if d.action in (DecisionAction.REROUTE, DecisionAction.RESCHEDULE):
            from fleet.loop import get_affected_vehicle_ids
            from fleet.routing.planner import preview_reroute_affected
            ev = next((e for e in self.state.events if e.id == d.event_id), None)
            stale = d.impact_estimate.get("_proposed_plan") or {}
            affected_vids = (get_affected_vehicle_ids(self.state, ev)
                             if ev is not None else list(stale.keys()))
            if affected_vids:
                _, proposed_plan = preview_reroute_affected(
                    self.state, self.components.optimizer, affected_vids)
            if not proposed_plan:
                proposed_plan = stale

        d.approval_status = ApprovalStatus.APPROVED
        d.approved_by = "human"
        d.approved_at = self.state.clock
        self._handle_sibling_decisions(d, ApprovalStatus.APPROVED)
        self.components.dispatcher.apply(self.state, d)

        from fleet.dispatch.dispatcher import RESOLVE_ACTIONS
        if d.action in RESOLVE_ACTIONS and self.state.total_orders_pending() > 0:
            from fleet.routing.planner import plan_total_minutes, reroute
            before = plan_total_minutes(self.state)

            if proposed_plan:
                # Reschedule stale timestamps: the plan was pre-computed when the
                # decision was queued; state.clock may have advanced before approve.
                # We shift so planned_arrival of the first unvisited stop equals
                # state.clock + leg_time_to_that_stop.  This puts frac≈0 in
                # _vehicle_position (vehicle starts at from_node, not at destination).
                for vid, new_vr in proposed_plan.items():
                    unvisited = sorted(
                        [s for s in new_vr.stops if s.actual_arrival is None],
                        key=lambda s: s.sequence)
                    if not unvisited:
                        continue
                    visited = sorted(
                        [s for s in new_vr.stops if s.actual_arrival is not None],
                        key=lambda s: s.sequence)
                    from_node = visited[-1].customer_id if visited else "DEPOT"
                    v = self.state.get_vehicle(vid)
                    wade = float(v.wade_capability) if v else 0.3
                    dist = shortest_times_from(self.state.road_graph, from_node, wade)
                    leg_min = dist.get(unvisited[0].customer_id, 1.0)
                    
                    is_driving = False
                    if visited:
                        last = visited[-1]
                        if last.actual_departure and self.state.clock >= last.actual_departure:
                            is_driving = True
                    # No visited stops → vehicle at/near DEPOT, allow full re-plan

                    if not is_driving:
                        ret_min = 0.0
                        if not visited and new_vr.start_time and new_vr.start_time < self.state.clock:
                            # Vehicle left DEPOT but hasn't visited any customer yet.
                            # Calculate how far along the original DEPOT->first_stop it is
                            # and store a return context so it animates back to DEPOT.
                            old_vr = self.state.plan.get(vid)
                            if old_vr and old_vr.stops and old_vr.start_time:
                                old_unv = sorted(
                                    [s for s in old_vr.stops if s.actual_arrival is None],
                                    key=lambda s: s.sequence)
                                if old_unv:
                                    old_to = old_unv[0].customer_id
                                    eff = max(1.0, shortest_times_from(
                                        self.state.road_graph, "DEPOT", wade).get(old_to, 1.0))
                                    frac = max(0.0, min(1.0, (
                                        self.state.clock - old_vr.start_time
                                    ).total_seconds() / (eff * 60.0)))
                                    if frac > 0.005:
                                        ret_eff = max(0.5, shortest_times_from(
                                            self.state.road_graph, old_to, wade).get("DEPOT", 1.0))
                                        ret_min = frac * ret_eff
                                        self._return_context[vid] = {
                                            'from_node': "DEPOT", 'to_node': old_to,
                                            'frac_at_approval': frac,
                                            'approval_clock': self.state.clock,
                                            'return_duration_min': ret_min,
                                        }
                        new_vr.start_time = self.state.clock + timedelta(minutes=ret_min)
                        target_arrival = self.state.clock + timedelta(minutes=ret_min + leg_min)

                        if unvisited[0].planned_arrival is not None:
                            shift = target_arrival - unvisited[0].planned_arrival
                            if abs(shift.total_seconds()) > 1:
                                for s in unvisited:
                                    if s.planned_arrival is not None:
                                        s.planned_arrival += shift
                                    if s.planned_departure is not None:
                                        s.planned_departure += shift
                self.state.plan.update(proposed_plan)
            else:
                # Fallback: full re-solve (e.g. REPRIORITIZE / REALLOCATE)
                reroute(self.state, self.components.optimizer)

            added = max(0.0, plan_total_minutes(self.state) - before)
            d.impact_estimate["added_delay_min"] = round(added, 1)
        return d

    def reject(self, decision_id: str):
        d = self._find_pending(decision_id)
        d.approval_status = ApprovalStatus.REJECTED
        d.approved_by = "human"
        d.approved_at = self.state.clock
        self._handle_sibling_decisions(d, ApprovalStatus.REJECTED)
        return d

    def _find_pending(self, decision_id: str):
        for d in self.state.get_pending_decisions():
            if d.id == decision_id:
                return d
        raise KeyError(f"no pending decision with id {decision_id!r}")
