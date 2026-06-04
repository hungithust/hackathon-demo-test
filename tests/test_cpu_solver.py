from datetime import datetime

from fleet.contracts.interfaces import RouteOptimizer
from fleet.contracts.dto import (
    RoutingProblem, FleetVehicleSpec, TaskSpec, RoutingSolution,
)
from fleet.routing.cpu_solver import CpuSolver


def _problem():
    t0 = datetime(2026, 6, 4, 6, 0)
    return RoutingProblem(
        locations=["DEPOT", "C1"], depot_id="DEPOT",
        time_matrix={"truck": [[0.0, 10.0], [10.0, 0.0]]},
        fleet=[FleetVehicleSpec("V1", 500, "truck", t0, t0)],
        tasks=[TaskSpec("C1", 20.0, t0, t0, 10.0, 1)],
    )


def test_conforms_to_protocol():
    assert isinstance(CpuSolver(), RouteOptimizer)


def test_returns_routing_solution():
    sol = CpuSolver().solve(_problem())
    assert isinstance(sol, RoutingSolution)
    # M1 stub schedules nothing yet; real greedy VRPTW lands in M3.
    assert sol.dropped == ["C1"]
    assert sol.feasible is False
    assert "V1" in sol.routes and sol.routes["V1"] == []
