from datetime import timedelta

import pytest

from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.routing.planner import (
    reroute, build_reroute_problem_for_vehicle, preview_reroute_affected,
)
from fleet.routing.matrix import build_time_matrix
from fleet.routing.cpu_solver import CpuSolver
from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import EdgeStatus, EventType, Stop, VehicleRoute
from config.settings import load_settings


def _seed_mid_edge_route(state):
    edge = state.road_graph.get_edge("DEPOT->C001")
    base = state.clock
    state.customers["C001"].orders = {"SKUX": 20}
    state.customers["C002"].orders = {"SKUY": 20}
    state.depot.inventory["SKUX"] = 200
    state.depot.inventory["SKUY"] = 200
    state.plan["V001"] = VehicleRoute(
        vehicle_id="V001",
        stops=[
            Stop(
                customer_id="C001",
                sequence=1,
                planned_arrival=base + timedelta(minutes=edge.effective_time),
                planned_departure=base + timedelta(minutes=edge.effective_time + 10),
                demand_kg=20,
            ),
            Stop(
                customer_id="C002",
                sequence=2,
                planned_arrival=base + timedelta(minutes=edge.effective_time + 30),
                planned_departure=base + timedelta(minutes=edge.effective_time + 40),
                demand_kg=20,
            ),
        ],
        start_time=base,
    )
    state.vehicles["V001"].route = state.plan["V001"]
    state.clock = base + timedelta(minutes=edge.effective_time / 2.0)
    return edge


def test_disrupt_edge_changes_graph_and_emits_event():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    evt = sim.disrupt_edge(s, "DEPOT->C001", EdgeStatus.BLOCKED)
    assert s.road_graph.get_edge("DEPOT->C001").status == EdgeStatus.BLOCKED
    assert evt.event_type == EventType.TRAFFIC or evt.event_type == EventType.FLOODED_AREA
    assert evt not in s.events  # detector owns persisted edge-condition events


def test_blocking_edge_reroutes_depot_to_c001_via_detour():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    locations = ["DEPOT", "C001", "C002", "C003", "C004"]
    direct = build_time_matrix(s.road_graph, locations, wade_capability=0.3)
    i, j = locations.index("DEPOT"), locations.index("C001")
    before = direct[i][j]

    sim.disrupt_edge(s, "DEPOT->C001", EdgeStatus.BLOCKED)

    after = build_time_matrix(s.road_graph, locations, wade_capability=0.3)
    assert after[i][j] > before     # forced onto a longer detour (or unreachable)


def test_reroute_returns_dropped_list_and_keeps_plan_consistent():
    s = build_sample_state()
    s.customers["C001"].orders = {"SKUX": 20}
    s.depot.inventory["SKUX"] = 200
    comps = build_components(load_settings())
    dropped = reroute(s, comps.optimizer)
    assert isinstance(dropped, list)
    assert s.plan                                   # a fresh plan was written


def test_current_edge_reroute_matrix_charges_partial_return_to_depot():
    s = build_sample_state()
    edge = _seed_mid_edge_route(s)

    problem = build_reroute_problem_for_vehicle(s, "V001")

    assert problem.locations[0] == "__POS_V001"
    virtual = problem.locations.index("__POS_V001")
    depot = problem.locations.index("DEPOT")
    matrix = problem.time_matrix[problem.fleet[0].veh_type]
    assert matrix[virtual][depot] == pytest.approx(edge.effective_time / 2.0)


def test_current_edge_preview_keeps_route_context_instead_of_locking_next_stop():
    s = build_sample_state()
    _seed_mid_edge_route(s)

    _, proposed = preview_reroute_affected(s, CpuSolver(), ["V001"])

    assert "V001" in proposed
    assert getattr(proposed["V001"], "_reroute_context")["edge_id"] == "DEPOT->C001"
