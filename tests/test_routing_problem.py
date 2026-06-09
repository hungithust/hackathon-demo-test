from fleet.routing.matrix import build_routing_problem, DEFAULT_SERVICE_TIME_MIN
from fleet.scenarios import build_sample_state


def test_problem_locations_depot_first():
    p = build_routing_problem(build_sample_state())
    assert p.depot_id == "DEPOT"
    assert p.locations[0] == "DEPOT"
    assert set(p.locations[1:]) == {"C001", "C002", "C003", "C004"}


def test_problem_has_truck_matrix_flood_aware():
    p = build_routing_problem(build_sample_state())
    assert "truck" in p.time_matrix
    di, ci = p.locations.index("DEPOT"), p.locations.index("C001")
    assert p.time_matrix["truck"][di][ci] == 10.0   # flood shortcut excluded (wade 0.3)


def test_problem_fleet_and_tasks():
    p = build_routing_problem(build_sample_state())
    assert len(p.fleet) == 3
    assert all(f.capacity_kg == 500 for f in p.fleet)
    assert {t.customer_id for t in p.tasks} == {"C001", "C002", "C003", "C004"}
    t001 = next(t for t in p.tasks if t.customer_id == "C001")
    assert t001.demand_kg == 15.0          # SKU001:10 + SKU002:5
    assert t001.service_time_min == DEFAULT_SERVICE_TIME_MIN
    assert t001.priority == 1


def test_problem_skips_customers_without_orders():
    s = build_sample_state()
    s.customers["C002"].orders.clear()
    p = build_routing_problem(s)
    assert "C002" not in p.locations
    assert all(t.customer_id != "C002" for t in p.tasks)


def test_problem_separate_matrix_per_vehicle_type():
    s = build_sample_state()
    s.vehicles["V001"].veh_type = "amphibious"
    s.vehicles["V001"].wade_capability = 0.6
    p = build_routing_problem(s)
    assert set(p.time_matrix.keys()) == {"truck", "amphibious"}
    di, ci = p.locations.index("DEPOT"), p.locations.index("C001")
    assert p.time_matrix["truck"][di][ci] == 10.0       # wade 0.3
    assert p.time_matrix["amphibious"][di][ci] == 6.0   # wade 0.6 -> flood shortcut


def test_problem_uses_vehicle_current_node_as_start():
    from fleet.contracts.state import VehicleRoute, Stop
    s = build_sample_state()
    # pretend V001 already delivered C001 and is now sitting at C001
    s.plan["V001"] = VehicleRoute(vehicle_id="V001", stops=[
        Stop(customer_id="C001", sequence=1, planned_arrival=s.clock,
             planned_departure=s.clock, actual_arrival=s.clock,
             actual_departure=s.clock)])
    s.vehicles["V001"].current_stop_index = 1
    p = build_routing_problem(s)
    v1 = next(f for f in p.fleet if f.id == "V001")
    assert v1.start_node == "C001"
    assert "C001" in p.locations           # start node is routable in the matrix
