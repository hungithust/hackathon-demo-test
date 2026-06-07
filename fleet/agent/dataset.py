"""Dataset factory for Sovereign Brain v2 (M-B). Drives the simulator over seeded
scenarios, grades each candidate action with the M-A oracle, keeps the proven-best
label, attaches reasoning (Sonnet Batch or a $0 templated fallback), and emits
train/serve-parity JSONL. Pure CPU; the Batch transport is injected so the test
suite never imports anthropic or touches the network."""

from fleet.contracts.state import WorldState, Event, DecisionAction
from fleet.agent.claude_agent import build_messages


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


def templated_reasoning(event: Event, scored) -> str:
    """A $0, deterministic justification built from the oracle's scored options."""
    best, best_cost = scored[0]
    base = (f"Simulated each option for the {event.event_type.value} on "
            f"{event.target}; chose {best.value} with the lowest realized cost "
            f"{best_cost:.1f}")
    alts = ", ".join(f"{a.value}={c:.1f}" for a, c in scored[1:])
    return base + (f" versus {alts}." if alts else ".")


def build_record(state: WorldState, event: Event, action: DecisionAction,
                 added_delay_min: float, reasoning: str) -> dict:
    """One JSONL row. Prompt fields come verbatim from build_messages (train/serve
    parity); the assistant turn is the strict _DECISION_SCHEMA object."""
    system, user = build_messages(state, event)
    return {
        "system": system,
        "user": user,
        "assistant": {
            "action": action.value,
            "reasoning": reasoning,
            "added_delay_min": round(float(added_delay_min), 2),
        },
    }
