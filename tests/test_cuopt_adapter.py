from datetime import datetime

from fleet.contracts.dto import (
    RoutingProblem, FleetVehicleSpec, TaskSpec,
)
from fleet.routing.cuopt_adapter import (
    to_cuopt_request, _base_time, _vehicle_type_keys,
)


def _problem():
    t0 = datetime(2026, 6, 4, 6, 0)
    t_end = datetime(2026, 6, 4, 18, 0)
    # locations: depot + two customers; one veh_type "truck"
    matrix = [
        [0.0, 10.0, 20.0],
        [10.0, 0.0, 15.0],
        [20.0, 15.0, 0.0],
    ]
    fleet = [
        FleetVehicleSpec("V001", 500, "truck", t0, t_end),
        FleetVehicleSpec("V002", 300, "truck", t0, t_end),
    ]
    tasks = [
        TaskSpec("C001", 40, datetime(2026, 6, 4, 7, 0),
                 datetime(2026, 6, 4, 9, 0), 10, priority=1),
        TaskSpec("C002", 60, datetime(2026, 6, 4, 8, 0),
                 datetime(2026, 6, 4, 12, 0), 10, priority=3),
    ]
    return RoutingProblem(
        locations=["DEPOT", "C001", "C002"], depot_id="DEPOT",
        time_matrix={"truck": matrix}, fleet=fleet, tasks=tasks)


def test_base_time_is_earliest_moment():
    p = _problem()
    # earliest of shift starts (06:00) and task tw_starts (07:00, 08:00)
    assert _base_time(p) == datetime(2026, 6, 4, 6, 0)


def test_vehicle_type_keys_are_stable_integers():
    p = _problem()
    assert _vehicle_type_keys(p) == {"truck": 0}


def test_request_has_cuopt_shape():
    p = _problem()
    req = to_cuopt_request(p)

    # matrices keyed by integer-as-string vehicle type, int-valued
    assert req["cost_matrix_data"]["data"]["0"] == [
        [0, 10, 20], [10, 0, 15], [20, 15, 0]]
    assert req["travel_time_matrix_data"]["data"]["0"][1][2] == 15

    td = req["task_data"]
    assert td["task_locations"] == [1, 2]              # indices into locations
    assert td["demand"] == [[40, 60]]                  # [n_dims][n_tasks]
    assert td["service_times"] == [10, 10]
    # tw in minutes from base (06:00): C001 07:00-09:00 -> 60..180
    assert td["task_time_windows"] == [[60, 180], [120, 360]]
    # penalty = 100000 * (5 - priority): priority 1 -> 400000, 3 -> 200000
    assert td["penalties"] == [400000, 200000]

    fd = req["fleet_data"]
    assert fd["vehicle_locations"] == [[0, 0], [0, 0]]  # start=end=depot index
    assert fd["capacities"] == [[500, 300]]             # [n_dims][n_vehicles]
    assert fd["vehicle_types"] == [0, 0]
    assert fd["vehicle_time_windows"] == [[0, 720], [0, 720]]  # 06:00..18:00


def test_unreachable_cell_becomes_forbidden_constant():
    p = _problem()
    p.time_matrix["truck"][0][2] = float("inf")
    req = to_cuopt_request(p)
    assert req["cost_matrix_data"]["data"]["0"][0][2] == 10_000_000
