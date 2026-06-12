from fleet.scenarios import build_sample_state
from fleet.routing.matrix import build_routing_problem


def test_build_problem_filters_customers():
    state = build_sample_state()
    prob = build_routing_problem(state, customer_ids={"C001"})
    task_ids = {t.customer_id for t in prob.tasks}
    assert task_ids == {"C001"}


def test_build_problem_filters_vehicles():
    state = build_sample_state()
    only = next(iter(state.vehicles))
    prob = build_routing_problem(state, vehicle_ids={only})
    assert {v.id for v in prob.fleet} == {only}


def test_build_problem_no_filter_is_unchanged():
    state = build_sample_state()
    prob = build_routing_problem(state)
    pending = {c for c in state.customers if sum(state.customers[c].orders.values()) > 0}
    assert {t.customer_id for t in prob.tasks} == pending


from fleet.routing.planner import reroute, _build_plan
from fleet.factory import build_components
from config.settings import load_settings


def _optimizer():
    return build_components(load_settings()).optimizer


def test_build_plan_respects_customer_filter():
    state = build_sample_state()
    _dropped, plan = _build_plan(state, _optimizer(), customer_ids={"C001"})
    planned = {s.customer_id for vr in plan.values() for s in vr.stops}
    assert planned <= {"C001"}


def test_reroute_respects_customer_filter():
    state = build_sample_state()
    reroute(state, _optimizer(), customer_ids={"C001", "C002"})
    planned = {s.customer_id for vr in state.plan.values() for s in vr.stops}
    assert planned <= {"C001", "C002"}


from fleet.routing.planner import plan_wave, plan_routes
from fleet.contracts.state import VehicleStatus


def test_plan_wave_only_plans_selected_customers():
    state = build_sample_state()
    plan_wave(state, _optimizer(), {"C001"})
    planned = {s.customer_id for vr in state.plan.values() for s in vr.stops}
    assert planned == {"C001"}


def test_plan_wave_merges_without_touching_busy_vehicles():
    state = build_sample_state()
    # Wave 1: dispatch C001 -> some vehicle gets a route.
    plan_wave(state, _optimizer(), {"C001"})
    busy_vid = next(vid for vid, vr in state.plan.items() if vr.stops)
    # Simulate the vehicle being out on the road (busy, not idle).
    state.vehicles[busy_vid].status = VehicleStatus.ON_ROUTE
    busy_route_before = state.plan[busy_vid]
    # Wave 2: dispatch C002 -> must use a DIFFERENT (idle) vehicle.
    plan_wave(state, _optimizer(), {"C002"})
    assert state.plan[busy_vid] is busy_route_before, "busy vehicle's route was replaced"
    planned = {s.customer_id for vr in state.plan.values() for s in vr.stops}
    assert {"C001", "C002"} <= planned


from fleet.loop import run_loop
from fleet.factory import build_components as _bc


def test_run_loop_no_auto_plan_leaves_world_undispatched():
    state = build_sample_state()
    settings = load_settings()
    run_loop(state, _bc(settings), n_ticks=2, settings=settings,
             logger=lambda *a, **k: None, auto_plan=False)
    assert state.plan == {}, "gated loop must not auto-plan the world"


def test_run_loop_default_still_auto_plans():
    state = build_sample_state()
    settings = load_settings()
    run_loop(state, _bc(settings), n_ticks=1, settings=settings,
             logger=lambda *a, **k: None)
    assert state.plan, "headless default must keep auto-planning"
