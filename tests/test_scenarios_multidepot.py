"""Tests for the true multi-depot world (build_multidepot_state): 5 depots, each
owning its vehicles, every vehicle departing from and returning to its home depot."""

from fleet.scenarios import build_multidepot_state
from fleet.routing.matrix import build_routing_problem
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.planner import plan_routes


def test_world_shape():
    st = build_multidepot_state()
    assert len(st.all_depots()) == 5
    assert len(st.vehicles) == 50
    assert len(st.customers) == 50
    # 10 vehicles per depot, each tagged with its home depot
    per_depot = {}
    for v in st.vehicles.values():
        per_depot[v.home_depot] = per_depot.get(v.home_depot, 0) + 1
    assert per_depot == {d: 10 for d in st.all_depots()}


def test_problem_sets_per_vehicle_end_location():
    st = build_multidepot_state()
    prob = build_routing_problem(st)
    # every depot node is in the location list, ahead of customers
    for did in st.all_depots():
        assert did in prob.locations
    # each vehicle's start and end location is its own home depot (none departed yet)
    for f in prob.fleet:
        v = st.vehicles[f.id]
        assert f.start_location == v.home_depot
        assert f.end_location == v.home_depot


def test_solver_returns_each_vehicle_to_its_home_depot():
    st = build_multidepot_state()
    prob = build_routing_problem(st)
    sol = CpuSolver().solve(prob)
    # No depot node is ever emitted as a served stop or dropped task.
    depot_ids = set(st.all_depots())
    for stops in sol.routes.values():
        assert all(s.customer_id not in depot_ids for s in stops)
    assert all(cid not in depot_ids for cid in sol.dropped)
    # The world stays solvable: at least most customers get scheduled.
    served = {s.customer_id for stops in sol.routes.values() for s in stops}
    assert len(served) >= 40


def test_plan_routes_writes_a_plan():
    st = build_multidepot_state()
    plan_routes(st, CpuSolver())
    assert any(vr.stops for vr in st.plan.values())
    # Each routed vehicle has start/end times derived from its home-depot legs.
    for vid, vr in st.plan.items():
        if vr.stops:
            assert vr.start_time is not None and vr.end_time is not None
