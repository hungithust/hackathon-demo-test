from fleet.scenarios import build_sample_state
from config.settings import load_settings
from fleet.factory import build_components
from fleet.loop import run_loop
from fleet.contracts.state import EventType, EventSeverity

s = build_sample_state()
settings = load_settings({})
comps = build_components(settings)
print('initial plan exists?', bool(s.plan))
evt = comps.simulator.inject_event(s, EventType.TRAFFIC, 'DEPOT->C001', EventSeverity.LOW)
print('after inject, events:', s.events)
run_loop(s, comps, n_ticks=1, settings=settings, logger=print)
print('decisions after loop:', s.decisions)
print('events after loop:', s.events)
print('plan after loop:', s.plan)
print('decisions for injected event:', [d for d in s.decisions if d.event_id == evt.id])
