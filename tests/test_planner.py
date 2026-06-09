from fleet.routing.planner import plan_routes
from fleet.routing.cpu_solver import CpuSolver
from fleet.contracts.state import VehicleRoute, Stop
from fleet.scenarios import build_sample_state


def test_plan_routes_populates_state_plan():
    s = build_sample_state()
    dropped = plan_routes(s, CpuSolver())
    assert dropped == []
    assert s.plan  # non-empty
    served = {st.customer_id for r in s.plan.values() for st in r.stops}
    assert served == {"C001", "C002", "C003", "C004"}
    for r in s.plan.values():
        assert isinstance(r, VehicleRoute)
        assert all(isinstance(st, Stop) for st in r.stops)
        assert [st.sequence for st in r.stops] == list(range(1, len(r.stops) + 1))


def test_plan_routes_stops_have_consistent_times():
    s = build_sample_state()
    plan_routes(s, CpuSolver())
    for r in s.plan.values():
        for st in r.stops:
            assert st.planned_departure >= st.planned_arrival
        assert r.start_time == r.stops[0].planned_arrival
        assert r.end_time == r.stops[-1].planned_departure


def test_plan_routes_only_routes_with_stops():
    s = build_sample_state()
    plan_routes(s, CpuSolver())
    # every stored route has at least one stop (empty routes are omitted)
    assert all(len(r.stops) >= 1 for r in s.plan.values())


def test_reroute_delay_minutes_sums_per_vehicle_change():
    from fleet.routing.planner import reroute_delay_minutes
    before = {"V001": 30.0, "V002": 10.0}     # vehicle_id -> planned drive minutes
    after = {"V001": 45.0, "V002": 10.0, "V003": 5.0}
    # V001 grew by 15, V003 is new work (+5), V002 unchanged -> +20 total
    assert reroute_delay_minutes(before, after) == 20.0
