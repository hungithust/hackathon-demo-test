from datetime import timedelta

from fleet.scenarios import build_sample_state
from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import Stop, VehicleRoute, VehicleStatus
from config.settings import load_settings


def _make_route(state, vid, customer_id):
    """One-stop route arriving at the very next tick boundary."""
    cust = state.customers[customer_id]
    arrival = state.clock + timedelta(minutes=load_settings().tick_minutes)
    stop = Stop(customer_id=customer_id, sequence=1,
                planned_arrival=arrival,
                planned_departure=arrival + timedelta(minutes=10),
                load_after_stop=0.0)
    state.plan[vid] = VehicleRoute(vehicle_id=vid, stops=[stop],
                                   start_time=arrival,
                                   end_time=stop.planned_departure)


def test_vehicle_visits_stop_on_schedule():
    s = build_sample_state()
    cust_id = "C001"
    s.customers[cust_id].orders = {"SKUX": 40}
    s.depot.inventory["SKUX"] = 100
    _make_route(s, "V001", cust_id)
    sim = WorldSimulator(load_settings())

    sim.tick(s)   # clock advances to the planned arrival

    stop = s.plan["V001"].stops[0]
    assert stop.actual_arrival is not None
    v = s.vehicles["V001"]
    assert v.current_stop_index == 1
    assert v.pos == s.customers[cust_id].location
    assert v.status == VehicleStatus.ON_ROUTE


def test_delivery_consumes_inventory_and_clears_orders():
    s = build_sample_state()
    s.customers["C001"].orders = {"SKUX": 40}
    s.depot.inventory["SKUX"] = 100
    sim = WorldSimulator(load_settings())

    sim._deliver(s, s.vehicles["V001"], "C001")

    assert s.depot.inventory["SKUX"] == 60
    assert s.customers["C001"].orders == {}


def test_inventory_never_goes_negative():
    s = build_sample_state()
    s.customers["C001"].orders = {"SKUX": 40}
    s.depot.inventory["SKUX"] = 10          # not enough stock
    sim = WorldSimulator(load_settings())

    sim._deliver(s, s.vehicles["V001"], "C001")

    assert s.depot.inventory["SKUX"] == 0
    assert s.customers["C001"].orders == {}


def test_vehicles_without_plan_are_untouched():
    s = build_sample_state()           # sample world has no plan
    sim = WorldSimulator(load_settings())
    before = {vid: v.status for vid, v in s.vehicles.items()}
    sim.tick(s)
    assert {vid: v.status for vid, v in s.vehicles.items()} == before
