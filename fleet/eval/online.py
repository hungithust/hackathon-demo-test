"""Online evaluation (Sovereign Brain v2, M-D): run a decision engine through the
real headless loop on a fixed scenario and read the realized outcome — on-time %,
cost, delay — plus decision latency. CPU-only and deterministic for rule/scoring."""

import time
from dataclasses import replace

from fleet.contracts.state import WorldState
from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.loop import run_loop
from fleet.agent.scoring_engine import _Weights
from fleet.agent.oracle import realized_cost


def _silent(*args, **kwargs) -> None:
    pass


def _delay_minutes(state: WorldState) -> float:
    total = 0.0
    for route in state.plan.values():
        for stop in route.stops:
            if stop.actual_arrival is None:
                continue
            cust = state.customers.get(stop.customer_id)
            if cust is None:
                continue
            overdue = (stop.actual_arrival - cust.time_window.end).total_seconds() / 60.0
            if overdue > 0:
                total += overdue
    return total


def _read_metrics(state: WorldState, settings) -> dict:
    delivered = on_time = 0
    for route in state.plan.values():
        for stop in route.stops:
            if stop.actual_arrival is None:
                continue
            delivered += 1
            cust = state.customers.get(stop.customer_id)
            if cust is not None and stop.actual_arrival <= cust.time_window.end:
                on_time += 1
    return {
        "delivered": delivered,
        "on_time": on_time,
        "on_time_pct": (on_time / delivered) if delivered else 0.0,
        "total_delay_min": _delay_minutes(state),
        "total_cost": realized_cost(state, _Weights(settings)),
    }


def engine_metrics(settings, decision_engine, n_ticks: int) -> dict:
    """Run `decision_engine` through the loop on the sample world for n_ticks and
    read the realized outcome. Other components come from the factory; only the
    decision engine is swapped, so the comparison is apples-to-apples."""
    state = build_sample_state()
    components = replace(build_components(settings), decision_engine=decision_engine)
    run_loop(state, components, n_ticks, settings, logger=_silent)
    return _read_metrics(state, settings)


def decide_latency_seconds(decision_engine, state: WorldState, events) -> float:
    """Wall-clock seconds for one decide() call (local NIM vs API round-trip)."""
    start = time.perf_counter()
    decision_engine.decide(state, events)
    return time.perf_counter() - start
