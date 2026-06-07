"""Simulator-as-oracle grader (Sovereign Brain v2, M-A). Instead of scoring an
action by a hardcoded effect table, *apply it to a clone of the world, roll the
simulation forward, and measure what actually happened*. `realized_cost` reads
that outcome reusing the M-D ScoringEngine weights so cost is in one unit.
Pure CPU, deterministic, no GPU/network — safe in the test suite."""

import copy
from dataclasses import replace
from typing import Callable, Optional

from fleet.contracts.state import (
    WorldState, Decision, DecisionAction, DecisionEngine, Event,
)
from fleet.dispatch.dispatcher import Dispatcher, RESOLVE_ACTIONS
from fleet.agent.scoring_engine import _Weights


def _priority_weight(priority: int) -> float:
    """Priority 1 (most urgent) -> 4 ... priority 4 -> 1. Mirrors the
    per-customer form of scoring_engine._priority_weight."""
    return float(5 - int(priority))


def realized_cost(state: WorldState, weights: "_Weights") -> float:
    """The world's ACTUAL outcome after a roll-forward; lower is better.

    cost = w_delay * total late-minutes (delivered stops past their window)
         + w_drop  * priority-weighted undelivered order units
         + w_sla   * count of customers with a breach (late OR undelivered)."""
    late_minutes = 0.0
    breached: set = set()

    for route in state.plan.values():
        for stop in route.stops:
            if stop.actual_arrival is None:
                continue
            cust = state.customers.get(stop.customer_id)
            if cust is None:
                continue
            overdue = (stop.actual_arrival - cust.time_window.end).total_seconds() / 60.0
            if overdue > 0:
                late_minutes += overdue
                breached.add(cust.id)

    drop_cost = 0.0
    for cid, cust in state.customers.items():
        units = sum(cust.orders.values())
        if units > 0:
            drop_cost += _priority_weight(cust.priority) * units
            breached.add(cid)

    return (weights.delay * late_minutes
            + weights.drop * drop_cost
            + weights.sla * float(len(breached)))


def roll_forward(simulator, state: WorldState, decision: Decision, horizon: int,
                 resolve: Optional[Callable[[WorldState], None]] = None,
                 freeze_world: bool = False,
                 enable_travel_time: bool = False) -> WorldState:
    """Clone (simulator, state, decision) TOGETHER — so the seeded rng is cloned
    with the world and every candidate sees an identical future — then apply the
    decision, optionally re-solve (resolve callback, only for RESOLVE_ACTIONS),
    and tick `horizon` times. Returns the rolled-forward clone; inputs are never
    mutated."""
    sim_c, state_c, dec_c = copy.deepcopy((simulator, state, decision))
    if enable_travel_time:
        sim_c.settings = replace(sim_c.settings, enable_travel_time=True)
    if freeze_world:
        sim_c.advance_only = True
    Dispatcher().apply(state_c, dec_c)
    if resolve is not None and dec_c.action in RESOLVE_ACTIONS:
        resolve(state_c)
    for _ in range(horizon):
        sim_c.tick(state_c)
    return state_c


def grade_action(simulator, state: WorldState, event: Event,
                 action: DecisionAction, settings, horizon: Optional[int] = None,
                 resolve: Optional[Callable[[WorldState], None]] = None) -> float:
    """Realized cost of taking `action` in response to `event`. Builds a probe
    Decision, rolls it forward, and grades the outcome. Horizon defaults to
    settings.oracle_horizon_ticks."""
    h = settings.oracle_horizon_ticks if horizon is None else horizon
    probe = Decision(
        id="ORACLE_PROBE", timestamp=state.clock, event_id=event.id, action=action,
        engine=DecisionEngine.RULE_BASED, description=f"oracle probe {action.value}")
    rolled = roll_forward(simulator, state, probe, h, resolve)
    return realized_cost(rolled, _Weights(settings))


def best_action(simulator, state: WorldState, event: Event, candidates, settings,
                horizon: Optional[int] = None,
                resolve: Optional[Callable[[WorldState], None]] = None):
    """Grade every candidate and return (best_action, best_cost, scored) where
    `scored` is the full [(action, cost), ...] list sorted by (cost, action.value)."""
    scored = sorted(
        ((a, grade_action(simulator, state, event, a, settings, horizon, resolve))
         for a in candidates),
        key=lambda t: (t[1], t[0].value))
    best, cost = scored[0]
    return best, cost, scored
