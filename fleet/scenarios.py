"""Deterministic sample worlds for tests, the headless loop, and demos.
Migrated from MOPHONG_Hackathon simple_simulator.create_sample_state with
spec schema applied (priority 1-4, veh_type/wade_capability, flood_level)."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fleet.contracts.state import (
    WorldState, Depot, Location, Vehicle, VehicleStatus, CustomerProfile,
    TimeWindow, RoadGraph, RoadNode, RoadEdge, EdgeStatus,
)
from fleet.detection.rules import RuleDetector
from fleet.geo.router import route
from fleet.geo.roster import HCM_CUSTOMERS


def build_sample_state(base_time: datetime = datetime(2026, 6, 4, 6, 0), urban_speed_kmh: float = 25.0) -> WorldState:
    """10-vehicle / 10-customer demo world with a realistic sparse road network.

    Topology:
      • 4 junction nodes (J_NW / J_NE / J_SE / J_SW) form a ring road.
      • DEPOT connects to every junction (main arteries).
      • Each customer has a direct DEPOT→Ci road AND connections to its 2 nearest
        junctions, giving real bypass options when the direct road is congested.
      • Nearby customer pairs (<= 5 km straight-line) get a direct edge.
    This means a traffic jam on DEPOT→Ci forces routing via junction (visible detour),
    unlike the old complete graph where every pair was always directly connected.
    """
    import math
    depot_loc = Location(10.8231, 106.6297, "1 Nguyen Hue, Q.1, HCM", "Kho Chinh HCM")
    depot = Depot(
        location=depot_loc,
        inventory={"SKU001": 5000, "SKU002": 3000, "SKU003": 4000},
        opening_time=base_time,
        closing_time=base_time + timedelta(hours=12),
    )

    # 10 vehicles
    vehicles = {}
    for i in range(1, 11):
        vid = f"V{i:03d}"
        vehicles[vid] = Vehicle(
            id=vid, capacity_kg=500, pos=depot_loc, current_load_kg=0,
            status=VehicleStatus.AT_DEPOT,
            shift_start=base_time, shift_end=base_time + timedelta(hours=48),
            veh_type="truck", wade_capability=0.3,
        )

    # 10 customers — first 10 from HCM roster, coordinates stretched 3× from center
    customers = {}
    center_lat, center_lng = 10.7760, 106.7000
    for cid, ctype, lat, lng, name, orders, prio, tw_s, tw_e, sla_h in HCM_CUSTOMERS[:10]:
        lat_s = center_lat + (lat - center_lat) * 3.0
        lng_s = center_lng + (lng - center_lng) * 3.0
        customers[cid] = CustomerProfile(
            id=cid, type=ctype,
            location=Location(lat_s, lng_s, name, name),
            orders=orders,
            time_window=TimeWindow(base_time, base_time + timedelta(hours=tw_e * 10)),
            priority=prio,
            sla_deadline=base_time + timedelta(hours=sla_h * 10),
        )

    # ── Road network nodes ──────────────────────────────────────────────────────
    # 4 junction nodes act as road intersections (not delivery destinations).
    # Positioned to form a ring that covers all 4 quadrants around the depot.
    junction_locs = {
        "J_NW": Location(10.880, 106.540, "Nút giao Tây Bắc", "Nút giao Tây Bắc"),
        "J_NE": Location(10.855, 106.650, "Nút giao Đông Bắc", "Nút giao Đông Bắc"),
        "J_SE": Location(10.775, 106.680, "Nút giao Đông Nam", "Nút giao Đông Nam"),
        "J_SW": Location(10.780, 106.580, "Nút giao Tây Nam", "Nút giao Tây Nam"),
    }

    nodes = {"DEPOT": RoadNode("DEPOT", depot_loc)}
    for jid, jloc in junction_locs.items():
        nodes[jid] = RoadNode(jid, jloc)
    for cid in customers:
        nodes[cid] = RoadNode(cid, customers[cid].location)

    def straight_km(a: str, b: str) -> float:
        la, lb = nodes[a].location, nodes[b].location
        return math.hypot(la.lat - lb.lat, la.lng - lb.lng) * 111.0

    edges: dict = {}
    adjacency: dict = {n: [] for n in nodes}

    def _add_edge(a: str, b: str, **kw):
        km = straight_km(a, b)
        mins = km * 60.0 / urban_speed_kmh
        e = RoadEdge(a, b, km, mins, **kw)
        if e.id not in edges:
            edges[e.id] = e
            adjacency[a].append(e.id)

    def _bidir(a: str, b: str, **kw):
        _add_edge(a, b, **kw)
        _add_edge(b, a, **kw)

    # 1. DEPOT ↔ all 4 junctions (main arteries)
    for jid in junction_locs:
        _bidir("DEPOT", jid)

    # 2. Ring road connecting adjacent junctions
    ring = ["J_NW", "J_NE", "J_SE", "J_SW"]
    for i in range(len(ring)):
        _bidir(ring[i], ring[(i + 1) % len(ring)])

    # 3. DEPOT ↔ each customer direct (main delivery roads — traffic jam targets)
    for cid in customers:
        _bidir("DEPOT", cid)

    # 4. Each customer ↔ its 2 nearest junctions (bypass alternatives)
    for cid in customers:
        cloc = customers[cid].location
        by_dist = sorted(junction_locs,
                         key=lambda jid: math.hypot(cloc.lat - junction_locs[jid].lat,
                                                     cloc.lng - junction_locs[jid].lng))
        for jid in by_dist[:2]:
            _bidir(cid, jid)

    # 5. Direct customer↔customer edges for geographically close pairs
    cids = list(customers.keys())
    for i in range(len(cids)):
        for j in range(i + 1, len(cids)):
            if straight_km(cids[i], cids[j]) <= 5.0:
                _bidir(cids[i], cids[j])

    # 6. Explicit demo road C001↔C002 (needed for the fixed traffic jam scenario)
    _bidir("C001", "C002")

    # 6b. Detour waypoint on the DEPOT→C001 corridor (the fixed demo jam edge).
    #     The demo jam covers the last 1/8 of DEPOT→C001 (frac 0.875→1.0, near
    #     C001). W001 sits ON that line at frac 0.8 — just BEFORE the jam, between
    #     DEPOT and the congested segment — and offers an alternate side-road
    #     W001→C001 that bypasses the jammed tail. So a rerouted vehicle can leave
    #     the main road at W001 ("đường vòng") and reach C001 via the detour
    #     instead of crawling through the jam, without swinging all the way out to
    #     a junction.  Costs:
    #       • DEPOT↔W001 — straight, mirrors the first 80% of the direct road (clear)
    #       • W001↔C001  — 1.3× its straight length: a genuine detour, longer than
    #         the 20% it replaces but cheaper than both the 10× jammed tail and the
    #         swing-out-to-junction bypass, so the reroute prefers turning off here.
    #     Normal (no jam) planning still prefers the 1.0× direct road; the detour
    #     only wins once DEPOT→C001 is congested.  W001 lives only in the road graph
    #     (never in `customers`), so the VRP never treats it as a delivery stop.
    if "C001" in nodes:
        t = 0.8  # fraction along DEPOT→C001, just before the jam start (0.875)
        dloc, c1loc = nodes["DEPOT"].location, nodes["C001"].location
        w_lat = dloc.lat + (c1loc.lat - dloc.lat) * t
        w_lng = dloc.lng + (c1loc.lng - dloc.lng) * t
        nodes["W001"] = RoadNode("W001", Location(w_lat, w_lng, "Điểm rẽ W001", "Điểm rẽ W001"))
        adjacency["W001"] = []
        _bidir("DEPOT", "W001")               # clear first leg (overlays 80% of direct)
        det_km = straight_km("W001", "C001") * 1.3   # detour side-road, longer than the straight remainder
        det_min = det_km * 60.0 / urban_speed_kmh
        for a, b in (("W001", "C001"), ("C001", "W001")):
            e = RoadEdge(a, b, det_km, det_min)
            if e.id not in edges:
                edges[e.id] = e
                adjacency[a].append(e.id)

    # 7. Synthetic junction branches — extra "ngã ba/ngã tư" bypass routes.
    #    For a corridor a→b we keep the existing direct edge AND add a parallel
    #    branch a → JX.. → b made of non-delivery junction nodes, bulged out to
    #    one side so it forms a visible alternate path. When the direct road is
    #    jammed/flooded the router detours through these junctions instead of
    #    having to swing all the way out to another customer. Junctions live only
    #    in the road graph (never in `customers`), so the VRP never treats them as
    #    delivery stops — Dijkstra/the cost matrix just travels through them.
    _jseq = [0]

    def _add_branch(a: str, b: str, n_mid: int = 2,
                    offset_frac: float = 0.35, side: int = 1) -> None:
        la, lb = nodes[a].location, nodes[b].location
        dlat, dlng = lb.lat - la.lat, lb.lng - la.lng
        length = math.hypot(dlat, dlng) or 1e-9
        # unit vector perpendicular to the a→b line, on the chosen side
        plat, plng = (-dlng / length) * side, (dlat / length) * side
        chain = [a]
        for k in range(1, n_mid + 1):
            t = k / (n_mid + 1)
            bulge = math.sin(t * math.pi) * length * offset_frac   # taper to 0 at ends
            jlat = la.lat + dlat * t + plat * bulge
            jlng = la.lng + dlng * t + plng * bulge
            _jseq[0] += 1
            jid = f"JX{_jseq[0]:02d}"
            label = f"Ngã rẽ {jid}"
            nodes[jid] = RoadNode(jid, Location(jlat, jlng, label, label))
            adjacency[jid] = []
            chain.append(jid)
        chain.append(b)
        for u, w in zip(chain[:-1], chain[1:]):
            _bidir(u, w)

    # A mix of DEPOT→customer and customer→customer corridors. DEPOT→C001 is the
    # fixed demo jam corridor (matches the example sketch). Sides alternate so the
    # branches don't overlap on the map.
    branch_corridors = [
        ("DEPOT", "C001", 2),   # fixed demo jam corridor (example image)
        ("DEPOT", "C003", 2),
        ("DEPOT", "C007", 2),
        ("C001", "C002", 2),
        ("C004", "C009", 1),
        ("C006", "C010", 2),
        ("C002", "C005", 1),
    ]
    for i, (a, b, nmid) in enumerate(branch_corridors):
        if a in nodes and b in nodes:
            _add_branch(a, b, n_mid=nmid, side=1 if i % 2 == 0 else -1)

    # Initial flood on the C005↔C006 direct edge so there's a visible flood marker
    # from the start.  Both nodes still reachable via DEPOT direct or junction bypass.
    for eid in ["C005->C006", "C006->C005"]:
        if eid in edges:
            edges[eid].status = EdgeStatus.FLOODED
            edges[eid].flood_level = 0.5

    state = WorldState(
        clock=base_time,
        depot=depot,
        customers=customers,
        vehicles=vehicles,
        road_graph=RoadGraph(nodes=nodes, edges=edges, adjacency=adjacency),
    )
    state.events.extend(RuleDetector().detect(state))
    return state


def build_real_state(graph, customers: Optional[List[tuple]] = None,
                     base_time: datetime = datetime(2026, 6, 4, 6, 0),
                     urban_speed_kmh: float = 25.0,
                     ) -> Tuple[WorldState, Dict[str, List[Tuple[float, float]]]]:
    """Real-map world: same logical structure as build_sample_state, but edge
    distance/time come from routing over `graph` (injected networkx graph) and a
    side-car geometry map (edge_id -> polyline) is returned for the UI. The graph
    is injected so this is testable offline and never forces an OSM load."""
    customers = customers if customers is not None else HCM_CUSTOMERS

    depot_loc = Location(10.8231, 106.6297, "1 Nguyen Hue, Q.1, HCM", "Kho Chinh HCM")
    depot = Depot(
        location=depot_loc,
        inventory={"SKU001": 5000, "SKU002": 3000, "SKU003": 4000},
        opening_time=base_time,
        closing_time=base_time + timedelta(hours=12),
    )

    vehicles = {}
    for i in range(1, 21):
        vid = f"V{i:03d}"
        vehicles[vid] = Vehicle(
            id=vid, capacity_kg=150, pos=depot_loc, current_load_kg=0,
            status=VehicleStatus.AT_DEPOT,
            shift_start=base_time, shift_end=base_time + timedelta(hours=48),
            veh_type="truck", wade_capability=0.3,
        )

    cust_objs = {}
    for i, (cid, ctype, lat, lng, name, orders, prio, tw_s, tw_e, sla_h) in enumerate(customers):
        if i in (2, 7):
            name = f"Kho Trung Chuyển {i}"
        cust_objs[cid] = CustomerProfile(
            id=cid, type=ctype,
            location=Location(lat, lng, name, name),
            orders=orders,
            time_window=TimeWindow(base_time, # Start immediately to avoid vehicles waiting at depot
                                   base_time + timedelta(hours=tw_e * 10)),
            priority=prio,
            sla_deadline=base_time + timedelta(hours=sla_h * 10),
        )

    nodes = {"DEPOT": RoadNode("DEPOT", depot_loc)}
    for cid in cust_objs:
        nodes[cid] = RoadNode(cid, cust_objs[cid].location)

    edges: Dict[str, RoadEdge] = {}
    adjacency: Dict[str, List[str]] = {n: [] for n in nodes}
    geometry: Dict[str, List[Tuple[float, float]]] = {}
    depot_latlng = (depot_loc.lat, depot_loc.lng)

    def _add(a, b, km, mins, poly, **kw):
        e = RoadEdge(a, b, km, mins, **kw)
        edges[e.id] = e
        adjacency[a].append(e.id)
        geometry[e.id] = poly

    # depot <-> every customer, routed both ways (reverse reuses the forward poly).
    for cid, c in cust_objs.items():
        r = route(graph, depot_latlng, (c.location.lat, c.location.lng),
                  urban_speed_kmh=urban_speed_kmh)
        _add("DEPOT", cid, r.distance_km, r.minutes, r.polyline)
        _add(cid, "DEPOT", r.distance_km, r.minutes, list(reversed(r.polyline)))

    # customer <-> customer roads (k nearest neighbours, routed over the real
    # graph). Without these the world is a star through DEPOT: blocking/flooding a
    # DEPOT->Cx edge isolates Cx with no alternative, so a reroute can never route
    # *around* anything. The k-nearest cap keeps this from becoming an O(N^2) OSM
    # routing blow-up while still giving every customer real detour options.
    import math as _math
    cids = list(cust_objs.keys())

    def _straight_km(a, b) -> float:
        la, lo = cust_objs[a].location, cust_objs[b].location
        return _math.hypot(la.lat - lo.lat, la.lng - lo.lng) * 111.0

    # Full pairwise connectivity: route between every customer pair so the routing
    # matrix has accurate OSM travel times for all (i, j) — not inflated indirect
    # approximations through intermediate customers.  With only k-nearest edges,
    # the Dijkstra used to build the cost matrix falls back to longer chain paths
    # for pairs without a direct edge, giving suboptimal VRP solutions and making
    # it impossible to find good detours when an edge is flooded/congested.
    for i, a in enumerate(cids):
        for b in cids[i + 1:]:
            if f"{a}->{b}" in edges:
                continue
            ca, cb = cust_objs[a].location, cust_objs[b].location
            r = route(graph, (ca.lat, ca.lng), (cb.lat, cb.lng),
                      urban_speed_kmh=urban_speed_kmh)
            _add(a, b, r.distance_km, r.minutes, r.polyline)
            _add(b, a, r.distance_km, r.minutes, list(reversed(r.polyline)))

    # Flood-prone parallel DEPOT<->C001 route (spec §6.9): shorter but FLOODED, so
    # standard trucks (wade 0.3 m) cannot use it while flooded — keeps M3's
    # per-veh_type matrix logic exercised. Geometry reuses the primary route.
    if "C001" in cust_objs:
        base = edges["DEPOT->C001"]
        poly = geometry["DEPOT->C001"]
        _add("DEPOT", "C001", base.distance_km * 0.6, base.base_time_minutes * 0.6,
             poly, id="DEPOT->C001#2", status=EdgeStatus.FLOODED, flood_level=0.5)
        _add("C001", "DEPOT", base.distance_km * 0.6, base.base_time_minutes * 0.6,
             list(reversed(poly)), id="C001->DEPOT#2",
             status=EdgeStatus.FLOODED, flood_level=0.5)

    state = WorldState(
        clock=base_time,
        depot=depot,
        customers=cust_objs,
        vehicles=vehicles,
        road_graph=RoadGraph(nodes=nodes, edges=edges, adjacency=adjacency),
    )
    
    # Run detector once so static conditions (e.g. flooded edges) appear at tick 0
    state.events.extend(RuleDetector().detect(state))
    
    return state, geometry
