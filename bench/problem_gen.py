"""Synthetic VRPTW problem generator for the CPU-vs-cuOpt benchmark.

Builds RoutingProblem objects directly (bypassing WorldState) so we can dial the
two axes the comparison needs:
  - number of depots   (1 depot  vs  5 depots — the hub-and-spoke vs multi-hub case)
  - number of customers (problem size — what actually drives solve cost)

Geometry: points dropped uniformly in an L×L km square. Travel time (minutes) =
euclidean_km / speed_kmh * 60, one shared veh_type ("truck"). Time windows span a
working day; demand/priority randomised but fleet capacity is sized to stay
feasible so both solvers face the *same* solvable instance and the only thing that
differs is the engine. Deterministic given `seed`."""

import math
import random
from datetime import datetime, timedelta

from fleet.contracts.dto import RoutingProblem, FleetVehicleSpec, TaskSpec

SPEED_KMH = 30.0
DAY = datetime(2026, 6, 12, 8, 0, 0)          # shift start 08:00
SHIFT_END = datetime(2026, 6, 12, 18, 0, 0)   # shift end   18:00


def _travel_min(a, b):
    km = math.hypot(a[0] - b[0], a[1] - b[1])
    return km / SPEED_KMH * 60.0


def make_problem(n_customers: int, n_depots: int = 1,
                 seed: int = 0, area_km: float = 40.0,
                 cust_per_vehicle: int = 8) -> RoutingProblem:
    """One VRPTW instance: n_depots depots, n_customers tasks, a fleet sized so the
    work is feasible. Vehicles are spread evenly across depots and return home."""
    rng = random.Random(seed)

    depot_pts = [(rng.uniform(0, area_km), rng.uniform(0, area_km))
                 for _ in range(n_depots)]
    cust_pts = [(rng.uniform(0, area_km), rng.uniform(0, area_km))
                for _ in range(n_customers)]

    depot_ids = [f"DEPOT{d}" for d in range(n_depots)]
    cust_ids = [f"C{i}" for i in range(n_customers)]
    locations = depot_ids + cust_ids
    pts = depot_pts + cust_pts

    # one shared time matrix (minutes) for veh_type "truck"
    n = len(locations)
    matrix = [[_travel_min(pts[i], pts[j]) for j in range(n)] for i in range(n)]
    time_matrix = {"truck": matrix}

    # fleet: ~ceil(n_customers / cust_per_vehicle) vehicles, round-robin across depots
    n_vehicles = max(n_depots, math.ceil(n_customers / cust_per_vehicle))
    fleet = []
    for v in range(n_vehicles):
        home = depot_ids[v % n_depots]
        fleet.append(FleetVehicleSpec(
            id=f"V{v}", capacity_kg=1000.0, veh_type="truck",
            shift_start=DAY, shift_end=SHIFT_END,
            start_location=home, end_location=home))

    # tasks: demand 10–80kg, wide-ish windows so instances stay feasible
    tasks = []
    for cid in cust_ids:
        start_off = rng.randint(0, 6)      # hours after 08:00
        width = rng.choice([3, 4, 6, 10])  # window width in hours
        tw_start = DAY + timedelta(hours=start_off)
        tw_end = min(SHIFT_END, tw_start + timedelta(hours=width))
        tasks.append(TaskSpec(
            customer_id=cid, demand_kg=float(rng.randint(10, 80)),
            tw_start=tw_start, tw_end=tw_end,
            service_time_min=10.0, priority=rng.randint(1, 4)))

    return RoutingProblem(locations=locations, depot_id=depot_ids[0],
                          time_matrix=time_matrix, fleet=fleet, tasks=tasks)