from datetime import datetime, timedelta

from config.settings import load_settings
from fleet.contracts.state import (
    WorldState, Depot, Location, CustomerProfile, TimeWindow, Stop, VehicleRoute,
)
from fleet.agent.scoring_engine import _Weights
from fleet.agent.oracle import realized_cost

_BASE = datetime(2026, 6, 4, 6, 0)


def _depot():
    return Depot(location=Location(0.0, 0.0, "d", "d"), inventory={},
                 opening_time=_BASE, closing_time=_BASE + timedelta(hours=12))


def _customer(orders, priority=1, window_hours=2):
    return CustomerProfile(
        id="C1", type="market", location=Location(0.0, 0.0, "c", "c"),
        orders=dict(orders), priority=priority,
        time_window=TimeWindow(_BASE, _BASE + timedelta(hours=window_hours)))


def test_realized_cost_counts_priority_weighted_drops():
    st = WorldState(clock=_BASE, depot=_depot(),
                    customers={"C1": _customer({"SKU001": 5}, priority=1)})
    w = _Weights(load_settings({}))
    # priority 1 -> weight 4; 5 undelivered units; 1 breached customer
    # cost = w_drop*4*5 + w_sla*1 = 50*20 + 50*1 = 1050
    assert realized_cost(st, w) == 1050.0


def test_realized_cost_zero_when_delivered_on_time():
    cust = _customer({}, priority=1)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1))
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    w = _Weights(load_settings({}))
    assert realized_cost(st, w) == 0.0


def test_realized_cost_charges_late_delivery():
    cust = _customer({}, priority=2, window_hours=1)
    stop = Stop(customer_id="C1", sequence=0,
                planned_arrival=_BASE + timedelta(hours=1),
                planned_departure=_BASE + timedelta(hours=1),
                actual_arrival=_BASE + timedelta(hours=1, minutes=30))  # 30 min late
    st = WorldState(clock=_BASE, depot=_depot(), customers={"C1": cust},
                    plan={"V1": VehicleRoute(vehicle_id="V1", stops=[stop])})
    w = _Weights(load_settings({}))
    # late 30 min, 1 breached customer, no drops -> 1*30 + 50*1 = 80
    assert realized_cost(st, w) == 80.0


def test_roll_forward_is_deterministic_and_pure():
    from fleet.contracts.state import Decision, DecisionAction, DecisionEngine
    from fleet.scenarios import build_sample_state
    from fleet.simulator.engine import WorldSimulator
    from fleet.agent.oracle import roll_forward

    settings = load_settings({})
    state = build_sample_state()
    sim = WorldSimulator(settings)
    dec = Decision(id="D", timestamp=state.clock, event_id=None,
                   action=DecisionAction.REPRIORITIZE,
                   engine=DecisionEngine.RULE_BASED, description="probe")
    before_clock = state.clock
    w = _Weights(settings)

    r1 = roll_forward(sim, state, dec, horizon=5)
    r2 = roll_forward(sim, state, dec, horizon=5)

    assert realized_cost(r1, w) == realized_cost(r2, w)   # identical future across branches
    assert r1.clock > before_clock                         # the clone advanced 5 ticks
    assert state.clock == before_clock                     # original state untouched
    assert state.sim_tick == 0                             # original simulator state untouched
    assert dec.executed_at is None                         # caller's decision untouched
