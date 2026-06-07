"""Dataset factory for Sovereign Brain v2 (M-B). Drives the simulator over seeded
scenarios, grades each candidate action with the M-A oracle, keeps the proven-best
label, attaches reasoning (Sonnet Batch or a $0 templated fallback), and emits
train/serve-parity JSONL. Pure CPU; the Batch transport is injected so the test
suite never imports anthropic or touches the network."""

from dataclasses import replace

from fleet.contracts.state import (
    WorldState, Event, DecisionAction, Decision, DecisionEngine,
    EventType, EventSeverity,
)
from fleet.agent.claude_agent import build_messages
from fleet.agent.scoring_engine import candidate_actions, _Weights
from fleet.agent.oracle import roll_forward, realized_cost
from fleet.scenarios import build_sample_state
from fleet.simulator.engine import WorldSimulator
from fleet.routing.planner import plan_routes


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


def grade_example(simulator, state: WorldState, event: Event, settings):
    """Roll every candidate action forward and grade by realized cost. Returns
    (best_action, best_realized_delay_min, scored) where scored is the full
    [(action, cost), ...] sorted by (cost, action.value)."""
    weights = _Weights(settings)
    horizon = settings.oracle_horizon_ticks
    results = []
    for a in candidate_actions(event.event_type):
        probe = Decision(
            id="ORACLE_PROBE", timestamp=state.clock, event_id=event.id, action=a,
            engine=DecisionEngine.RULE_BASED, description=f"oracle probe {a.value}")
        rolled = roll_forward(simulator, state, probe, horizon)
        results.append((a, realized_cost(rolled, weights),
                        realized_delay_minutes(rolled)))
    results.sort(key=lambda t: (t[1], t[0].value))
    best, _best_cost, best_delay = results[0]
    scored = [(a, c) for a, c, _ in results]
    return best, best_delay, scored


# (event_type, severity, target_kind) — spans all 4 disruption classes + severities.
DATASET_EVENT_SPECS = [
    (EventType.TRAFFIC, EventSeverity.MEDIUM, "edge"),
    (EventType.FLOODED_AREA, EventSeverity.HIGH, "edge"),
    (EventType.DEMAND_SURGE, EventSeverity.MEDIUM, "customer"),
    (EventType.URGENT_ORDER, EventSeverity.HIGH, "customer"),
    (EventType.INVENTORY_SHORTAGE, EventSeverity.HIGH, "sku"),
    (EventType.VEHICLE_BREAKDOWN, EventSeverity.CRITICAL, "vehicle"),
]


def _pick_target(state: WorldState, kind: str) -> str:
    """Deterministic target for an injected event (first id in sorted order)."""
    if kind == "edge":
        return sorted(state.road_graph.edges)[0]
    if kind == "customer":
        return sorted(state.customers)[0]
    if kind == "sku":
        return sorted(state.depot.inventory)[0]
    if kind == "vehicle":
        return sorted(state.vehicles)[0]
    raise ValueError(f"unknown target kind: {kind}")


def make_example(seed: int, spec, settings, optimizer, warmup_ticks: int = 6):
    """Build a planned, warmed-up world for one (seed, spec) and inject the event.
    Returns (simulator, state, event). Deterministic given the inputs."""
    s = replace(settings, seed=seed)
    state = build_sample_state()
    sim = WorldSimulator(s)
    plan_routes(state, optimizer)                 # solve routes so actions matter
    for _ in range(warmup_ticks):
        sim.tick(state)
    event_type, severity, kind = spec
    event = sim.inject_event(state, event_type, _pick_target(state, kind), severity)
    return sim, state, event


def iter_examples(settings, n_seeds: int, optimizer, warmup_ticks: int = 6):
    """Yield (seed, (simulator, state, event)) over seeds x DATASET_EVENT_SPECS."""
    for seed in range(settings.seed, settings.seed + n_seeds):
        for spec in DATASET_EVENT_SPECS:
            yield seed, make_example(seed, spec, settings, optimizer, warmup_ticks)


_REASONING_SYSTEM = (
    "You justify dispatch decisions for a real-time delivery-fleet system. Given a "
    "disruption event and the action that was chosen, write one or two sentences "
    "explaining why that action best protects on-time delivery and safety. Justify "
    "the GIVEN action; do not propose a different one.")


def split_by_seed(records, holdout_frac: float):
    """Split [(seed, record), ...] into (train, test) so no seed appears in both —
    the last ceil(holdout_frac * n_seeds) distinct seeds become the test set."""
    seeds = sorted({s for s, _ in records})
    n_test = max(1, round(holdout_frac * len(seeds))) if seeds else 0
    test_seeds = set(seeds[len(seeds) - n_test:]) if n_test else set()
    train = [r for s, r in records if s not in test_seeds]
    test = [r for s, r in records if s in test_seeds]
    return train, test


def _reasoning_prompt(state: WorldState, event: Event, action: DecisionAction) -> str:
    _system, user = build_messages(state, event)
    return (user + f"\n\nThe chosen action is: {action.value}. "
                   "Justify it in one or two sentences.")


def build_reasoning_requests(examples):
    """Transport-agnostic request descriptors (plain dicts) for the Batch transport."""
    return [{"custom_id": e["custom_id"], "system": _REASONING_SYSTEM,
             "user": _reasoning_prompt(e["state"], e["event"], e["action"])}
            for e in examples]


def batch_reasoning(examples, submit=None) -> dict:
    """Reasoning per example custom_id. `submit(requests) -> {custom_id: reasoning}`
    is injected (Sonnet Batch in production); any id the transport doesn't return —
    or submit=None — falls back to the $0 templated reasoning."""
    raw = {}
    if submit is not None and examples:
        raw = submit(build_reasoning_requests(examples)) or {}
    out = {}
    for e in examples:
        cid = e["custom_id"]
        out[cid] = raw.get(cid) or templated_reasoning(e["event"], e["scored"])
    return out


def default_batch_submit(settings):
    """Lazy real transport: Sonnet 4.6 via the Message Batches API (thinking off,
    guided-JSON reasoning). Imported here so the suite never needs anthropic."""
    import json
    import time
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    client = anthropic.Anthropic(api_key=(settings.anthropic_api_key or None))
    schema = {"type": "object", "properties": {"reasoning": {"type": "string"}},
              "required": ["reasoning"], "additionalProperties": False}

    def submit(reqs):
        batch = client.messages.batches.create(requests=[
            Request(custom_id=r["custom_id"],
                    params=MessageCreateParamsNonStreaming(
                        model="claude-sonnet-4-6", max_tokens=256,
                        thinking={"type": "disabled"}, system=r["system"],
                        output_config={"format": {"type": "json_schema",
                                                   "schema": schema}},
                        messages=[{"role": "user", "content": r["user"]}]))
            for r in reqs])
        while client.messages.batches.retrieve(batch.id).processing_status != "ended":
            time.sleep(30)
        out = {}
        for res in client.messages.batches.results(batch.id):
            if res.result.type == "succeeded":
                msg = res.result.message
                text = next((b.text for b in msg.content if b.type == "text"), "")
                try:
                    out[res.custom_id] = json.loads(text).get("reasoning", "")
                except Exception:
                    pass
        return out

    return submit
