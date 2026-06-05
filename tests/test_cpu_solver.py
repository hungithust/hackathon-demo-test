from datetime import datetime, timedelta

from fleet.contracts.interfaces import RouteOptimizer
from fleet.contracts.dto import (
    RoutingProblem, FleetVehicleSpec, TaskSpec, RoutingSolution,
)
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.matrix import build_routing_problem
from fleet.scenarios import build_sample_state


def test_conforms_to_protocol():
    assert isinstance(CpuSolver(), RouteOptimizer)


def test_serves_all_feasible_sample_customers():
    problem = build_routing_problem(build_sample_state())
    sol = CpuSolver().solve(problem)
    assert isinstance(sol, RoutingSolution)
    assert sol.feasible is True
    served = {st.customer_id for stops in sol.routes.values() for st in stops}
    assert served == {"C001", "C002", "C003", "C004"}
    assert sol.dropped == []


def test_each_customer_served_at_most_once():
    problem = build_routing_problem(build_sample_state())
    sol = CpuSolver().solve(problem)
    served = [st.customer_id for stops in sol.routes.values() for st in stops]
    assert len(served) == len(set(served))


def test_respects_capacity():
    problem = build_routing_problem(build_sample_state())
    sol = CpuSolver().solve(problem)
    cap = {f.id: f.capacity_kg for f in problem.fleet}
    demand = {t.customer_id: t.demand_kg for t in problem.tasks}
    for vid, stops in sol.routes.items():
        assert sum(demand[st.customer_id] for st in stops) <= cap[vid]


def test_respects_time_windows():
    problem = build_routing_problem(build_sample_state())
    sol = CpuSolver().solve(problem)
    tw = {t.customer_id: (t.tw_start, t.tw_end) for t in problem.tasks}
    for stops in sol.routes.values():
        for st in stops:
            start, end = tw[st.customer_id]
            assert start <= st.arrival <= end


def test_drops_infeasible_customer():
    t0 = datetime(2026, 6, 5, 6, 0)
    # shift 6:00-7:00; C1 window 6:00-6:05 but 10 min away -> cannot be served
    problem = RoutingProblem(
        locations=["DEPOT", "C1"], depot_id="DEPOT",
        time_matrix={"truck": [[0.0, 10.0], [10.0, 0.0]]},
        fleet=[FleetVehicleSpec("V1", 500, "truck", t0, t0 + timedelta(hours=1))],
        tasks=[TaskSpec("C1", 20.0, t0, t0 + timedelta(minutes=5), 10.0, 1)],
    )
    sol = CpuSolver().solve(problem)
    assert sol.dropped == ["C1"]
    assert sol.routes["V1"] == []


def test_deterministic():
    problem = build_routing_problem(build_sample_state())
    a = CpuSolver().solve(problem)
    b = CpuSolver().solve(problem)
    norm = lambda s: {v: [(st.customer_id, st.arrival) for st in stops]
                      for v, stops in s.routes.items()}
    assert norm(a) == norm(b)
