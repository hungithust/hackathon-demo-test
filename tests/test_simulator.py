from datetime import timedelta

from fleet.contracts.interfaces import Simulator
from fleet.contracts.state import EventType, EventSeverity
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
