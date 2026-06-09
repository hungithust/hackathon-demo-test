from datetime import timedelta

from fleet.contracts.interfaces import Simulator
from fleet.contracts.state import EventType, EventSeverity, Stop, VehicleRoute, EdgeStatus
from fleet.simulator.engine import WorldSimulator
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def test_conforms_to_protocol():
    assert isinstance(WorldSimulator(load_settings()), Simulator)


def test_tick_advances_clock_and_counter():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"TICK_MINUTES": "5"}))
    start = s.clock
    sim.tick(s)
    assert s.sim_tick == 1
    assert s.clock == start + timedelta(minutes=5)


def test_inject_event_appends_active_event():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    evt = sim.inject_event(s, EventType.TRAFFIC, "DEPOT->C001", EventSeverity.HIGH)
    assert evt.ended_at is None
    assert evt in s.get_active_events()
    assert evt.id.startswith("EVT_")


def test_tick_freeze_mode_skips_exogenous_updates():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    sim.advance_only = True
    before_orders = {cid: dict(c.orders) for cid, c in s.customers.items()}
    before_inventory = dict(s.depot.inventory)
    sim.tick(s)
    assert {cid: c.orders for cid, c in s.customers.items()} == before_orders
    assert s.depot.inventory == before_inventory


def test_live_travel_time_blocks_schedule_driven_delivery():
    base = build_sample_state().clock
    s = build_sample_state(base)
    s.plan = {
        "V001": VehicleRoute(
            vehicle_id="V001",
            stops=[Stop(
                customer_id="C001", sequence=1,
                planned_arrival=base + timedelta(minutes=10),
                planned_departure=base + timedelta(minutes=20),
            )],
            start_time=base + timedelta(minutes=10),
            end_time=base + timedelta(minutes=20),
        )
    }
    s.road_graph.edges["DEPOT->C001"].status = EdgeStatus.BLOCKED
    s.road_graph.edges["DEPOT->C001#2"].status = EdgeStatus.BLOCKED
    sim = WorldSimulator(load_settings({"ENABLE_TRAVEL_TIME": "1"}))

    sim.tick(s)
    sim.tick(s)  # clock = base + 10 min

    stop = s.plan["V001"].stops[0]
    assert stop.actual_arrival is None


def test_sudden_events_do_not_perturb_demand_stream():
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    from config.settings import load_settings

    base = build_sample_state()
    sim_a = WorldSimulator(load_settings(env={"ENABLE_SUDDEN_EVENTS": "0"}))
    for _ in range(8):
        sim_a.tick(base)
    demand_off = {c.id: dict(c.orders) for c in base.customers.values()}

    base2 = build_sample_state()
    sim_b = WorldSimulator(load_settings(env={"ENABLE_SUDDEN_EVENTS": "1"}))
    for _ in range(8):
        sim_b.tick(base2)
    demand_on = {c.id: dict(c.orders) for c in base2.customers.values()}

    assert demand_off == demand_on   # injection uses its own rng; demand identical
