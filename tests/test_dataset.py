from datetime import datetime, timedelta

from fleet.contracts.state import (
    WorldState, Depot, Location, CustomerProfile, TimeWindow, Stop, VehicleRoute,
    DecisionAction,
)
from fleet.agent.dataset import realized_delay_minutes, is_informative

_BASE = datetime(2026, 6, 4, 6, 0)


def _depot():
    return Depot(location=Location(0.0, 0.0, "d", "d"), inventory={},
                 opening_time=_BASE, closing_time=_BASE + timedelta(hours=12))


def test_realized_delay_sums_overdue_minutes():
    cust = CustomerProfile(
        id="C1", type="market", location=Location(0.0, 0.0, "c", "c"), orders={},
        time_window=TimeWindow(_BASE, _BASE + timedelta(hours=1)), priority=2)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1, minutes=20))  # 20 min late
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    assert realized_delay_minutes(st) == 20.0


def test_realized_delay_zero_when_on_time():
    cust = CustomerProfile(
        id="C1", type="market", location=Location(0.0, 0.0, "c", "c"), orders={},
        time_window=TimeWindow(_BASE, _BASE + timedelta(hours=2)), priority=2)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1))
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    assert realized_delay_minutes(st) == 0.0


def test_is_informative_uses_cost_gap():
    scored = [(DecisionAction.REPRIORITIZE, 10.0), (DecisionAction.CANCEL, 60.0)]
    assert is_informative(scored, min_gap=1.0) is True
    assert is_informative(scored, min_gap=100.0) is False
    assert is_informative([(DecisionAction.REROUTE, 5.0)], min_gap=1.0) is False
    assert is_informative([], min_gap=1.0) is False


def test_templated_reasoning_names_choice_and_alternatives():
    from fleet.contracts.state import Event, EventType, EventSeverity, DecisionAction
    from fleet.agent.dataset import templated_reasoning
    evt = Event(id="E1", event_type=EventType.INVENTORY_SHORTAGE, target="SKU001",
                severity=EventSeverity.HIGH, started_at=_BASE)
    scored = [(DecisionAction.REPRIORITIZE, 12.0),
              (DecisionAction.DEFER, 20.0),
              (DecisionAction.CANCEL, 60.0)]
    text = templated_reasoning(evt, scored)
    assert text == (
        "Simulated each option for the inventory_shortage on SKU001; "
        "chose reprioritize with the lowest realized cost 12.0 "
        "versus defer=20.0, cancel=60.0.")


def test_templated_reasoning_handles_single_candidate():
    from fleet.contracts.state import Event, EventType, EventSeverity, DecisionAction
    from fleet.agent.dataset import templated_reasoning
    evt = Event(id="E2", event_type=EventType.TRAFFIC, target="e1",
                severity=EventSeverity.MEDIUM, started_at=_BASE)
    text = templated_reasoning(evt, [(DecisionAction.REROUTE, 8.0)])
    assert text == (
        "Simulated each option for the traffic on e1; "
        "chose reroute with the lowest realized cost 8.0.")


def test_build_record_matches_build_messages_and_schema():
    from fleet.contracts.state import Event, EventType, EventSeverity, DecisionAction
    from fleet.agent.claude_agent import build_messages
    from fleet.agent.dataset import build_record
    from fleet.scenarios import build_sample_state

    state = build_sample_state()
    evt = Event(id="E1", event_type=EventType.DEMAND_SURGE, target="C001",
                severity=EventSeverity.MEDIUM, started_at=state.clock)
    record = build_record(state, evt, DecisionAction.REPRIORITIZE, 3.0, "because.")

    system, user = build_messages(state, evt)
    assert record["system"] == system            # train/serve parity
    assert record["user"] == user
    assert record["assistant"] == {
        "action": "reprioritize", "reasoning": "because.", "added_delay_min": 3.0}
    # assistant turn carries exactly the _DECISION_SCHEMA keys
    assert set(record["assistant"]) == {"action", "reasoning", "added_delay_min"}


def test_grade_example_is_deterministic_and_returns_a_candidate():
    from config.settings import load_settings
    from fleet.contracts.state import Event, EventType, EventSeverity
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    from fleet.agent.scoring_engine import candidate_actions
    from fleet.agent.dataset import grade_example

    settings = load_settings({})
    state = build_sample_state()
    sim = WorldSimulator(settings)
    evt = Event(id="EVT_S", event_type=EventType.INVENTORY_SHORTAGE, target="SKU001",
                severity=EventSeverity.HIGH, started_at=state.clock)
    state.events.append(evt)

    action, delay, scored = grade_example(sim, state, evt, settings)
    assert action in candidate_actions(EventType.INVENTORY_SHORTAGE)
    assert delay >= 0.0
    assert [a for a, _ in scored] == sorted(
        candidate_actions(EventType.INVENTORY_SHORTAGE),
        key=lambda a: (dict(scored)[a], a.value))     # sorted by (cost, action.value)
    # determinism
    action2, delay2, scored2 = grade_example(sim, state, evt, settings)
    assert (action, delay, scored) == (action2, delay2, scored2)


def test_make_example_injects_event_and_is_deterministic():
    from config.settings import load_settings
    from fleet.contracts.state import EventType, EventSeverity
    from fleet.factory import build_components
    from fleet.agent.dataset import make_example, DATASET_EVENT_SPECS

    settings = load_settings({})
    optimizer = build_components(settings).optimizer
    spec = (EventType.INVENTORY_SHORTAGE, EventSeverity.HIGH, "sku")

    sim1, state1, evt1 = make_example(7, spec, settings, optimizer)
    assert evt1 in state1.events                       # the event is present in the world
    assert evt1.event_type == EventType.INVENTORY_SHORTAGE
    assert state1.plan                                 # routes were solved

    # determinism: same seed+spec -> same injected event id + target
    sim2, state2, evt2 = make_example(7, spec, settings, optimizer)
    assert (evt2.id, evt2.target, evt2.severity) == (evt1.id, evt1.target, evt1.severity)


def test_iter_examples_spans_all_event_specs_per_seed():
    from config.settings import load_settings
    from fleet.factory import build_components
    from fleet.agent.dataset import iter_examples, DATASET_EVENT_SPECS

    settings = load_settings({})
    optimizer = build_components(settings).optimizer
    seen = {evt.event_type for _seed, (_sim, _state, evt)
            in iter_examples(settings, n_seeds=1, optimizer=optimizer)}
    assert seen == {spec[0] for spec in DATASET_EVENT_SPECS}


def test_split_by_seed_has_no_seed_leak():
    from fleet.agent.dataset import split_by_seed
    records = [(s, {"row": s}) for s in [1, 1, 2, 2, 3, 3, 4, 4]]
    train, test = split_by_seed(records, holdout_frac=0.25)
    train_seeds = {r["row"] for r in train}
    test_seeds = {r["row"] for r in test}
    assert test_seeds and not (train_seeds & test_seeds)   # disjoint -> no scenario leak
    assert test_seeds == {4}                                # last 25% of 4 seeds = seed 4


def test_batch_reasoning_falls_back_to_templated_per_missing_id():
    from fleet.contracts.state import Event, EventType, EventSeverity, DecisionAction
    from fleet.agent.dataset import batch_reasoning, templated_reasoning
    evt = Event(id="E1", event_type=EventType.DEMAND_SURGE, target="C001",
                severity=EventSeverity.MEDIUM, started_at=_BASE)
    scored = [(DecisionAction.REPRIORITIZE, 10.0), (DecisionAction.REALLOCATE, 30.0)]
    from fleet.scenarios import build_sample_state
    state = build_sample_state()
    examples = [
        {"custom_id": "ex-0", "state": state, "event": evt,
         "action": DecisionAction.REPRIORITIZE, "scored": scored},
        {"custom_id": "ex-1", "state": state, "event": evt,
         "action": DecisionAction.REPRIORITIZE, "scored": scored},
    ]

    # injected transport: only ex-0 gets a teacher reasoning
    def fake_submit(reqs):
        assert {r["custom_id"] for r in reqs} == {"ex-0", "ex-1"}
        return {"ex-0": "teacher says reprioritize."}

    out = batch_reasoning(examples, submit=fake_submit)
    assert out["ex-0"] == "teacher says reprioritize."
    assert out["ex-1"] == templated_reasoning(evt, scored)   # fallback

    # submit=None -> fully $0 templated path
    out0 = batch_reasoning(examples, submit=None)
    assert out0 == {"ex-0": templated_reasoning(evt, scored),
                    "ex-1": templated_reasoning(evt, scored)}


def test_grade_full_returns_sorted_action_cost_delay():
    from config.settings import load_settings
    from fleet.contracts.state import Event, EventType, EventSeverity
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    from fleet.agent.scoring_engine import candidate_actions
    from fleet.agent.dataset import grade_full

    settings = load_settings({})
    state = build_sample_state()
    sim = WorldSimulator(settings)
    evt = Event(id="EVT_F", event_type=EventType.INVENTORY_SHORTAGE, target="SKU001",
                severity=EventSeverity.HIGH, started_at=state.clock)
    state.events.append(evt)

    full = grade_full(sim, state, evt, settings)
    cands = candidate_actions(EventType.INVENTORY_SHORTAGE)
    assert [a for a, _c, _d in full] == sorted(
        cands, key=lambda a: (dict((aa, cc) for aa, cc, _ in full)[a], a.value))
    assert len(full) == len(cands)
    assert all(d >= 0.0 for _a, _c, d in full)
    assert full == grade_full(sim, state, evt, settings)        # deterministic
