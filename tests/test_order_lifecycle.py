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
