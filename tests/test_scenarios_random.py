"""Random scenario factory: distinct, reproducible, solvable worlds."""
from fleet.scenarios import make_scenarios, build_random_state, ScenarioSpec
from fleet.ui.controller import SimulationController
from fleet.routing import planner


def test_make_scenarios_are_distinct():
    specs = make_scenarios(1000, seed=1)
    assert len(specs) == 1000
    # seeds unique, and the maps genuinely differ (centres + sizes)
    assert len({s.seed for s in specs}) == 1000
    centres = {(round(s.center_lat, 3), round(s.center_lng, 3)) for s in specs}
    assert len(centres) > 900          # almost all distinct map centres
    sizes = {(s.n_customers, s.n_vehicles) for s in specs}
    assert len(sizes) > 20             # varied fleet/customer counts


def test_make_scenarios_reproducible():
    a = make_scenarios(50, seed=7)
    b = make_scenarios(50, seed=7)
    assert a == b                      # frozen dataclass equality
    assert make_scenarios(50, seed=8) != a


def test_build_random_state_is_valid_and_solvable():
    spec = make_scenarios(1, seed=42)[0]
    state = build_random_state(spec)
    assert len(state.customers) == spec.n_customers
    assert len(state.vehicles) == spec.n_vehicles
    assert "DEPOT" in state.road_graph.nodes
    # every customer reachable from depot directly
    for cid in state.customers:
        assert f"DEPOT->{cid}" in state.road_graph.edges
    # the solver produces a plan without raising
    planner.plan_routes(state, SimulationController(state=state).components.optimizer)


def test_random_state_drives_through_controller():
    state = build_random_state(ScenarioSpec(seed=3, n_customers=8, n_vehicles=4))
    c = SimulationController(state=state, synthetic_geometry=True)
    snap0 = c.snapshot()
    c.step(3)
    snap1 = c.snapshot()
    assert snap1["sim_tick"] == 3
    assert snap1["sim_tick"] > snap0["sim_tick"]
    assert c.geometry            # synthetic_geometry produced drawable roads
    import json
    json.dumps(snap1)            # snapshot stays JSON-safe for the API