from datetime import datetime

from fleet.contracts.dto import (
    FleetVehicleSpec, TaskSpec, RoutingProblem, SolvedStop, RoutingSolution,
)


def test_build_routing_problem():
    t0 = datetime(2026, 6, 4, 6, 0)
    prob = RoutingProblem(
        locations=["DEPOT", "C1"],
        depot_id="DEPOT",
        time_matrix={"truck": [[0.0, 10.0], [10.0, 0.0]]},
        fleet=[FleetVehicleSpec(id="V1", capacity_kg=500, veh_type="truck",
                                shift_start=t0, shift_end=t0)],
        tasks=[TaskSpec(customer_id="C1", demand_kg=20.0, tw_start=t0, tw_end=t0,
                        service_time_min=10.0, priority=1)],
    )
    assert prob.time_matrix["truck"][0][1] == 10.0
    assert prob.fleet[0].capacity_kg == 500


def test_routing_solution_defaults():
    sol = RoutingSolution(
        routes={"V1": [SolvedStop(customer_id="C1", arrival=datetime(2026, 6, 4, 7),
                                  departure=datetime(2026, 6, 4, 7, 10),
                                  load_after=480.0)]},
        dropped=[])
    assert sol.feasible is True
    assert sol.metrics == {}
    assert sol.routes["V1"][0].load_after == 480.0
