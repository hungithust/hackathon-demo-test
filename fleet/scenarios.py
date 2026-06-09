"""Deterministic sample worlds for tests, the headless loop, and demos.
Migrated from MOPHONG_Hackathon simple_simulator.create_sample_state with
spec schema applied (priority 1-4, veh_type/wade_capability, flood_level)."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fleet.contracts.state import (
    WorldState, Depot, Location, Vehicle, VehicleStatus, CustomerProfile,
    TimeWindow, RoadGraph, RoadNode, RoadEdge, EdgeStatus,
)
from fleet.geo.router import route
from fleet.geo.roster import HCM_CUSTOMERS


def build_sample_state(base_time: datetime = datetime(2026, 6, 4, 6, 0), urban_speed_kmh: float = 25.0) -> WorldState:
    import math
    import random
    
    depot_loc = Location(10.8231, 106.6297, "1 Nguyen Hue, Q.1, HCM", "Kho Chinh HCM")
    depot = Depot(
        location=depot_loc,
        inventory={"SKU001": 5000, "SKU002": 3000, "SKU003": 4000},
        opening_time=base_time,
        closing_time=base_time + timedelta(hours=12),
    )

    # Small deterministic fleet for the sample world (3 vehicles)
    vehicles = {}
    for i in range(1, 4):
        vid = f"V{i:03d}"
        vehicles[vid] = Vehicle(
            id=vid, capacity_kg=500, pos=depot_loc, current_load_kg=0,
            status=VehicleStatus.AT_DEPOT,
            shift_start=base_time, shift_end=base_time + timedelta(hours=48),
            veh_type="truck", wade_capability=0.3,
        )

    # Use a small curated subset of HCM_CUSTOMERS for the sample world (C001..C004)
    customers = {}
    for i, (cid, ctype, lat, lng, name, orders, prio, tw_s, tw_e, sla_h) in enumerate(HCM_CUSTOMERS[:4]):
        if i in (2, 7):
            name = f"Kho Trung Chuyển {i}"
        customers[cid] = CustomerProfile(
            id=cid, type=ctype,
            location=Location(lat, lng, name, name),
            orders=dict(orders),
            time_window=TimeWindow(base_time + timedelta(hours=tw_s),
                                   base_time + timedelta(hours=tw_e * 10)),
            priority=prio,
            sla_deadline=base_time + timedelta(hours=sla_h * 10),
        )

    nodes = {"DEPOT": RoadNode("DEPOT", depot_loc)}
    for cid in customers:
        nodes[cid] = RoadNode(cid, customers[cid].location)

    def dist(l1, l2):
        return math.hypot(l1.lat - l2.lat, l1.lng - l2.lng) * 111.0

    # Build a small, deterministic graph: depot <-> each customer and a ring
    edges = {}
    adjacency = {n: [] for n in nodes}

    def _add_edge(a, b, km, mins, **kw):
        e = RoadEdge(a, b, km, mins, **kw)
        if e.id not in edges:
            edges[e.id] = e
            adjacency[a].append(e.id)

    cids = list(customers.keys())
    # connect depot to all with computed km/mins
    for cid in cids:
        km = dist(depot_loc, customers[cid].location)
        mins = km * 60 / urban_speed_kmh
        # Override DEPOT->C001 base time to 2.0 minutes to keep tests deterministic
        if cid == "C001":
            mins = 2.0
            km = urban_speed_kmh * mins / 60.0
        _add_edge("DEPOT", cid, km, mins)
        _add_edge(cid, "DEPOT", km, mins)

    # connect a simple ring between customers; inflate non-depot edges so the
    # direct DEPOT->C001 route remains the shortest for determinism in tests
    for i in range(len(cids)):
        c1, c2 = cids[i], cids[(i+1) % len(cids)]
        km = dist(customers[c1].location, customers[c2].location)
        mins = km * 60 / urban_speed_kmh * 3.0
        _add_edge(c1, c2, km, mins)
        _add_edge(c2, c1, km, mins)

    # a single extra deterministic link (inflated) for connectivity
    km_c13 = dist(customers["C001"].location, customers["C003"].location)
    mins_c13 = km_c13 * 60 / urban_speed_kmh * 3.0
    _add_edge("C001", "C003", km_c13, mins_c13)
    _add_edge("C003", "C001", km_c13, mins_c13)

    # Flood-prone parallel DEPOT<->C001 route (shortcut)
    if "C001" in customers:
        base = edges["DEPOT->C001"]
        # create a faster but flood-prone parallel edge (60% of base time)
        _add_edge("DEPOT", "C001", base.distance_km * 0.6, base.base_time_minutes * 0.6,
                  id="DEPOT->C001#2", status=EdgeStatus.FLOODED, flood_level=0.5)
        _add_edge("C001", "DEPOT", base.distance_km * 0.6, base.base_time_minutes * 0.6,
                  id="C001->DEPOT#2", status=EdgeStatus.FLOODED, flood_level=0.5)

    return WorldState(
        clock=base_time,
        depot=depot,
        customers=customers,
        vehicles=vehicles,
        road_graph=RoadGraph(nodes=nodes, edges=edges, adjacency=adjacency),
    )


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
            id=vid, capacity_kg=500, pos=depot_loc, current_load_kg=0,
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
            orders=dict(orders),
            time_window=TimeWindow(base_time + timedelta(hours=tw_s),
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

    k = min(4, len(cids) - 1)
    for a in cids:
        nearest = sorted((b for b in cids if b != a),
                         key=lambda b: _straight_km(a, b))[:k]
        for b in nearest:
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
    return state, geometry
