"""Deterministic sample worlds for tests, the headless loop, and demos.
Migrated from MOPHONG_Hackathon simple_simulator.create_sample_state with
spec schema applied (priority 1-4, veh_type/wade_capability, flood_level)."""

from datetime import datetime, timedelta

from fleet.contracts.state import (
    WorldState, Depot, Location, Vehicle, VehicleStatus, CustomerProfile,
    TimeWindow, RoadGraph, RoadNode, RoadEdge,
)


def build_sample_state(base_time: datetime = datetime(2026, 6, 4, 6, 0)) -> WorldState:
    """1 depot, 3 vehicles, 4 customers in HCM District 1."""
    depot_loc = Location(10.8231, 106.6297, "1 Nguyen Hue, Q.1, HCM", "Kho Chinh HCM")
    depot = Depot(
        location=depot_loc,
        inventory={"SKU001": 100, "SKU002": 50, "SKU003": 80},
        opening_time=base_time,
        closing_time=base_time + timedelta(hours=12),
    )

    vehicles = {}
    for i in range(1, 4):
        vid = f"V{i:03d}"
        vehicles[vid] = Vehicle(
            id=vid, capacity_kg=500, pos=depot_loc, current_load_kg=0,
            status=VehicleStatus.AT_DEPOT,
            shift_start=base_time, shift_end=base_time + timedelta(hours=10),
            veh_type="truck", wade_capability=0.3,
        )

    cust_specs = [
        ("C001", "supermarket", 10.8050, 106.6300, "BigC Q.1",
         {"SKU001": 10, "SKU002": 5}, 1, 1, 3, 4),
        ("C002", "market", 10.7748, 106.6987, "Cho Ben Thanh",
         {"SKU001": 20}, 2, 1.5, 3.5, 5),
        ("C003", "convenience_store", 10.8150, 106.6150, "MiniMart Le Loi",
         {"SKU002": 15, "SKU003": 8}, 3, 2, 4, 6),
        ("C004", "restaurant", 10.8300, 106.6400, "Nha hang A Chau",
         {"SKU003": 30}, 2, 1.75, 4, 5.5),
    ]
    customers = {}
    for cid, ctype, lat, lng, name, orders, prio, tw_s, tw_e, sla_h in cust_specs:
        customers[cid] = CustomerProfile(
            id=cid, type=ctype,
            location=Location(lat, lng, name, name),
            orders=orders,
            time_window=TimeWindow(base_time + timedelta(hours=tw_s),
                                   base_time + timedelta(hours=tw_e)),
            priority=prio,
            sla_deadline=base_time + timedelta(hours=sla_h),
        )

    nodes = {"DEPOT": RoadNode("DEPOT", depot_loc)}
    for cid in customers:
        nodes[cid] = RoadNode(cid, customers[cid].location)

    # depot <-> every customer (both directions) so every stop is reachable.
    edge_list = [
        ("DEPOT", "C001", 2.0, 10.0), ("DEPOT", "C002", 4.0, 15.0),
        ("DEPOT", "C003", 2.5, 12.0), ("DEPOT", "C004", 3.0, 14.0),
        ("C001", "C002", 3.0, 12.0), ("C002", "C003", 2.5, 10.0),
        ("C003", "C004", 2.0, 8.0), ("C004", "DEPOT", 3.5, 15.0),
    ]
    edges = {}
    adjacency = {n: [] for n in nodes}

    def _add_edge(a, b, km, mins, **kw):
        e = RoadEdge(a, b, km, mins, **kw)
        edges[e.id] = e
        adjacency[a].append(e.id)

    for a, b, km, mins in edge_list:
        _add_edge(a, b, km, mins)
        _add_edge(b, a, km, mins)

    return WorldState(
        clock=base_time,
        depot=depot,
        customers=customers,
        vehicles=vehicles,
        road_graph=RoadGraph(nodes=nodes, edges=edges, adjacency=adjacency),
    )
