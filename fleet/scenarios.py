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


def build_multidepot_state(
        n_depots: int = 5,
        vehicles_per_depot: int = 10,
        customers_per_depot: int = 10,
        base_time: datetime = datetime(2026, 6, 4, 6, 0),
        urban_speed_kmh: float = 25.0,
        seed: int = 7,
) -> WorldState:
    """True multi-depot demo world: ``n_depots`` warehouses, each owning
    ``vehicles_per_depot`` vehicles and serving its own cluster of
    ``customers_per_depot`` delivery points. Every vehicle departs from and
    returns to its home depot (Vehicle.home_depot), so the VRP is genuinely
    multi-depot — not a single hub.

    Defaults give 5 depots × 10 vehicles (50 trucks) and 50 customers.

    Topology (deterministic from ``seed``):
      • Depots sit close together on a small ring near the HCM centre, every depot
        linked to every other (short inter-depot arteries).
      • Each depot's customer cluster sits FAR out in that depot's direction, so the
        depot→delivery legs are long and clearly visible (routes, jams, detours).
      • Every depot has a direct road to EVERY customer, so the cost matrix carries a
        real travel time for every (depot, point) pair and any depot can serve any
        point.
      • Delivery points are scattered (with a minimum separation) across a wide disc
        around the centre — not tight per-depot clumps — so the map reads like a real
        city with dispersed stops and crossing roads. Each point's home depot is just
        its nearest depot.
      • Each customer links to its 2 globally-nearest neighbours, so neighbouring
        stops (possibly served by different depots) are connected and a blocked
        depot→Ci road has a customer-to-customer bypass.
    """
    import math
    import random as _random

    rng = _random.Random(seed)
    center_lat, center_lng = 10.7760, 106.7000
    depot_radius = 0.022       # ~2.4 km centre→depot: depots clustered close together
    cust_r_min, cust_r_max = 0.045, 0.190   # ~5–21 km: stops spread far across a wide disc
    bc_candidates = 24         # best-candidate samples/point → even (blue-noise) spacing

    # ── Depots on a small ring near the centre ────────────────────────────────
    depots: Dict[str, Depot] = {}
    depot_locs: Dict[str, Location] = {}
    for d in range(n_depots):
        did = f"D{d + 1}"
        angle = 2.0 * math.pi * d / n_depots
        dlat = center_lat + depot_radius * math.cos(angle)
        dlng = center_lng + depot_radius * math.sin(angle) * 1.05
        loc = Location(dlat, dlng, f"Kho {did} HCM", f"Kho {did}")
        depot_locs[did] = loc
        depots[did] = Depot(
            location=loc,
            inventory={"SKU001": 5000, "SKU002": 3000, "SKU003": 4000},
            opening_time=base_time,
            closing_time=base_time + timedelta(hours=12),
            id=did,
        )

    # ── Vehicles: vehicles_per_depot per depot, home_depot set ────────────────
    vehicles: Dict[str, Vehicle] = {}
    vnum = 0
    for did in depots:
        for _ in range(vehicles_per_depot):
            vnum += 1
            vid = f"V{vnum:03d}"
            vehicles[vid] = Vehicle(
                id=vid, capacity_kg=500, pos=depot_locs[did], current_load_kg=0,
                status=VehicleStatus.AT_DEPOT,
                shift_start=base_time, shift_end=base_time + timedelta(hours=48),
                veh_type="truck", wade_capability=0.3, home_depot=did,
            )

    # ── Customers scattered across a wide disc (area-uniform), kept min_sep apart ─
    skus = ["SKU001", "SKU002", "SKU003"]
    customers: Dict[str, CustomerProfile] = {}
    cluster_of: Dict[str, str] = {}   # customer id -> home depot id (nearest depot)
    placed: List[Tuple[float, float]] = []
    total_customers = n_depots * customers_per_depot

    def _sample_point() -> Tuple[float, float]:
        ang = rng.uniform(0.0, 2.0 * math.pi)
        r = cust_r_min + (cust_r_max - cust_r_min) * math.sqrt(rng.random())  # area-uniform
        return (center_lat + r * math.cos(ang), center_lng + r * math.sin(ang) * 1.05)

    for cnum in range(1, total_customers + 1):
        cid = f"C{cnum:03d}"
        # Mitchell best-candidate: of bc_candidates random points, keep the one
        # farthest from all already-placed stops → even blue-noise spread (no clumps,
        # large gaps), so the roads between stops are long and clearly visible.
        if not placed:
            lat, lng = _sample_point()
        else:
            best, best_d = None, -1.0
            for _ in range(bc_candidates):
                clat, clng = _sample_point()
                d = min(math.hypot(clat - pl, clng - pn) for pl, pn in placed)
                if d > best_d:
                    best_d, best = d, (clat, clng)
            lat, lng = best
        placed.append((lat, lng))
        n_sku = rng.randint(1, 2)
        orders = {sku: rng.randint(5, 25) for sku in rng.sample(skus, n_sku)}
        prio = rng.randint(1, 4)
        tw_e = rng.uniform(3.0, 6.0)
        sla_h = tw_e + rng.uniform(0.5, 1.5)
        customers[cid] = CustomerProfile(
            id=cid, type="store",
            location=Location(lat, lng, f"Điểm giao {cid}", f"Điểm giao {cid}"),
            orders=orders,
            time_window=TimeWindow(base_time, base_time + timedelta(hours=tw_e * 10)),
            priority=prio,
            sla_deadline=base_time + timedelta(hours=sla_h * 10),
        )
        # home depot = nearest depot
        cluster_of[cid] = min(
            depots, key=lambda d: math.hypot(lat - depot_locs[d].lat,
                                             lng - depot_locs[d].lng))

    # ── Road network ──────────────────────────────────────────────────────────
    nodes: Dict[str, RoadNode] = {}
    for did, loc in depot_locs.items():
        nodes[did] = RoadNode(did, loc)
    for cid, c in customers.items():
        nodes[cid] = RoadNode(cid, c.location)

    def straight_km(a: str, b: str) -> float:
        la, lb = nodes[a].location, nodes[b].location
        return math.hypot(la.lat - lb.lat, la.lng - lb.lng) * 111.0

    edges: Dict[str, RoadEdge] = {}
    adjacency: Dict[str, list] = {n: [] for n in nodes}

    def _add_edge(a: str, b: str) -> None:
        km = straight_km(a, b)
        mins = km * 60.0 / urban_speed_kmh
        e = RoadEdge(a, b, km, mins)
        if e.id not in edges:
            edges[e.id] = e
            adjacency[a].append(e.id)

    def _bidir(a: str, b: str) -> None:
        _add_edge(a, b)
        _add_edge(b, a)

    # 1. Inter-depot arteries (full mesh keeps the graph connected)
    depot_ids = list(depots)
    for i in range(len(depot_ids)):
        for j in range(i + 1, len(depot_ids)):
            _bidir(depot_ids[i], depot_ids[j])

    # 2. Every depot ↔ EVERY customer (direct delivery roads). This gives the cost
    #    matrix a real travel time for every (depot, point) pair, so any depot can
    #    serve any point; the home-cluster road is short, cross-cluster roads long.
    by_cluster: Dict[str, list] = {did: [] for did in depots}
    for cid, did in cluster_of.items():
        by_cluster[did].append(cid)
        # Giữ lại đường nối với Depot gần nhất để đảm bảo luôn có ít nhất 1 đường về Depot
        _bidir(did, cid)

    # 3. K-nearest customer↔customer edges: connect each delivery point to its 3 closest neighbours
    #    to keep the graph sparse (around 200 edges) and visually readable, while ensuring connectivity.
    all_cids = list(customers)
    for cid in all_cids:
        others = [c for c in all_cids if c != cid]
        others.sort(key=lambda c: straight_km(cid, c))
        for other in others[:3]:
            _bidir(cid, other)

    # 4. Synthetic junction branches — parallel "ngã ba/ngã tư" bypass routes, like
    #    build_sample_state. For a corridor a→b we keep the direct edge AND add a
    #    branch a → JX.. → b bulged to one side, so a jam/flood on the direct road
    #    has a visible detour through non-delivery junction nodes (never in
    #    `customers`, so the VRP only travels through them).
    _jseq = [0]

    def _add_branch(a: str, b: str, n_mid: int = 2,
                    offset_frac: float = 0.35, side: int = 1) -> None:
        la, lb = nodes[a].location, nodes[b].location
        dlat, dlng = lb.lat - la.lat, lb.lng - la.lng
        length = math.hypot(dlat, dlng) or 1e-9
        plat, plng = (-dlng / length) * side, (dlat / length) * side
        chain = [a]
        for k in range(1, n_mid + 1):
            t = k / (n_mid + 1)
            bulge = math.sin(t * math.pi) * length * offset_frac
            jlat = la.lat + dlat * t + plat * bulge
            jlng = la.lng + dlng * t + plng * bulge
            _jseq[0] += 1
            jid = f"JX{_jseq[0]:02d}"
            nodes[jid] = RoadNode(jid, Location(jlat, jlng, f"Ngã rẽ {jid}", f"Ngã rẽ {jid}"))
            adjacency[jid] = []
            chain.append(jid)
        chain.append(b)
        for u, w in zip(chain[:-1], chain[1:]):
            _bidir(u, w)

    # 5. Per cluster: a detour waypoint (W) on the depot→nearest-customer road plus
    #    a couple of junction branches, mirroring the sample world's "đường vòng".
    wseq = 0
    for i, (did, cids) in enumerate(by_cluster.items()):
        if not cids:
            continue
        dloc = depot_locs[did]
        by_near = sorted(cids, key=lambda c: straight_km(did, c))
        cnear = by_near[0]

        # Detour waypoint at frac 0.8 along depot→cnear: depot→W is the clear first
        # leg; W→cnear is a 1.3× side-road that bypasses a jam on the direct road.
        wseq += 1
        wid = f"W{wseq:03d}"
        t = 0.8
        cloc = customers[cnear].location
        w_lat = dloc.lat + (cloc.lat - dloc.lat) * t
        w_lng = dloc.lng + (cloc.lng - dloc.lng) * t
        nodes[wid] = RoadNode(wid, Location(w_lat, w_lng, f"Điểm rẽ {wid}", f"Điểm rẽ {wid}"))
        adjacency[wid] = []
        _bidir(did, wid)
        det_km = straight_km(wid, cnear) * 1.3
        det_min = det_km * 60.0 / urban_speed_kmh
        for a, b in ((wid, cnear), (cnear, wid)):
            e = RoadEdge(a, b, det_km, det_min)
            if e.id not in edges:
                edges[e.id] = e
                adjacency[a].append(e.id)

        # A junction branch on depot→2nd-nearest customer, and one on an intra-cluster pair.
        if len(by_near) >= 2:
            _add_branch(did, by_near[1], n_mid=2, side=1 if i % 2 == 0 else -1)
        if len(cids) >= 2:
            _add_branch(cids[0], cids[1], n_mid=1, side=-1 if i % 2 == 0 else 1)

    # 6. Initial flood per cluster on a customer↔customer edge (both endpoints stay
    #    reachable via their direct depot road or the junction branch added above),
    #    so the map shows flood markers with a real detour from tick 0.
    for did, cids in by_cluster.items():
        if len(cids) >= 2:
            for eid in (f"{cids[0]}->{cids[1]}", f"{cids[1]}->{cids[0]}"):
                if eid in edges:
                    edges[eid].status = EdgeStatus.FLOODED
                    edges[eid].flood_level = 0.5

    primary = depots[depot_ids[0]]
    state = WorldState(
        clock=base_time,
        depot=primary,                 # back-compat primary (shared inventory/hours)
        customers=customers,
        vehicles=vehicles,
        depots=depots,
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
