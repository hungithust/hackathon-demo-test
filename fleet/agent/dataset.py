"""Dataset factory for Sovereign Brain v2 (M-B). Drives the simulator over seeded
scenarios, grades each candidate action with the M-A oracle, keeps the proven-best
label, attaches reasoning (Sonnet Batch or a $0 templated fallback), and emits
train/serve-parity JSONL. Pure CPU; the Batch transport is injected so the test
suite never imports anthropic or touches the network."""

from fleet.contracts.state import WorldState


def realized_delay_minutes(state: WorldState) -> float:
    """Total minutes that delivered stops arrived past their customer's window."""
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


def is_informative(scored, min_gap: float) -> bool:
    """True when the best/worst realized-cost gap is at least `min_gap` — i.e. the
    candidate actions actually differ, so the example teaches something."""
    if not scored:
        return False
    costs = [c for _, c in scored]
    return (max(costs) - min(costs)) >= min_gap
