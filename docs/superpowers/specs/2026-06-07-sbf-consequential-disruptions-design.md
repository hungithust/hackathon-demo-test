# Sovereign Brain v2 — M-F: Consequential Disruptions (design)

> Makes disruptions actually change the simulated outcome, so the oracle can
> distinguish candidate actions for **all** event types — not just
> `inventory_shortage`. Config-gated; default path unchanged so the existing
> suite stays green.

**Status:** design approved (matrix-replay movement; 2026-06-07).
**Depends on:** M-A oracle, M-B dataset factory. **Unblocks:** meaningful M-D/M-E.

---

## 1. Problem (measured, not assumed)

Running the M-B factory, the oracle produces a usable (best≠worst) cost gap for
**only 1 of 6 event types**:

```
gen_dataset --seeds 20  ->  informative_fraction = 0.167,
event_types = {inventory_shortage: 20}      # all other 5 types filtered out
```

Direct oracle probe (`grade_full`) at horizons 12 → 72 confirms the other five
types grade **identically across every candidate action** (gap = 0.0):

```
traffic            gap=0.0   defer=13400 reroute=13400 reschedule=13400
flooded_area       gap=0.0   defer=13400 reroute=13400 reschedule=13400
demand_surge       gap=0.0   accelerate=13400 reallocate=13400 reprioritize=13400
urgent_order       gap=0.0   accelerate=13400 reallocate=13400 reprioritize=13400
vehicle_breakdown  gap=0.0   cancel=13400 reallocate=13400 reschedule=13400
inventory_shortage gap=13200 cancel=13400 reprioritize=13400 defer=26600   <- only one
```

A single-class dataset trains a brain that is no better than the rule engine on
5/6 disruption types — collapsing the "outcome-verified, multi-class decision
LLM" value proposition.

## 2. Root cause (three compounding facts)

1. **Movement is schedule-driven.** `WorldSimulator._advance_vehicles` delivers a
   stop the moment `stop.planned_arrival <= state.clock`, ignoring live edge
   status. A blocked/flooded/congested edge changes the *planned* time matrix
   (`build_routing_problem`) but never the *actual* travel — so reroute/
   reschedule/reallocate cannot change the realized outcome.
2. **`inject_event` harms nothing.** `make_example` calls
   `sim.inject_event(...)`, which only appends an `Event` object. The edge is
   never blocked, the vehicle is never set `BROKEN`, the demand is never spiked.
   With no harm in the world, no action has anything to mitigate.
3. **Grading never re-solves and never freezes demand.** `grade_full` rolls
   actions forward with `roll_forward(sim, state, probe, horizon)` — no `resolve`
   callback, so RESOLVE_ACTIONS (reroute/reschedule/reprioritize/reallocate) are
   silent no-ops; and demand keeps regenerating during the roll-forward, so
   `realized_cost` is dominated by fresh, action-invariant orders.

Increasing the horizon does **not** help (verified to 72 ticks = 6h sim): cost
just grows with standing demand while the gap stays 0.

## 3. Design

Four coupled changes. (1) is the simulator capability; (2)–(4) make the M-B
factory use it to manufacture genuine trade-offs. All gated so defaults are
untouched.

### 3.1 Travel-time-aware movement (matrix-replay) — `enable_travel_time`

New setting `enable_travel_time: bool = False`. When **False** (default),
`_advance_vehicles` keeps today's schedule-driven behavior byte-for-byte (the
existing 52-test suite is unaffected). When **True**, movement is replayed
against the **live** road graph using the existing Dijkstra primitive
`shortest_times_from(graph, source, wade_capability)` (which already honors
`RoadEdge.is_passable` for BLOCKED/FLOODED and `effective_time` for congestion):

```
for each vehicle with a route (skip BROKEN/MAINTENANCE):
    last = highest-sequence stop with actual_arrival set
    if last:  cur_node, cur_time = last.customer_id, last.actual_departure
    else:     cur_node, cur_time = "DEPOT", depot.opening_time
    for stop in route.stops (in order, skipping visited):
        dist = shortest_times_from(graph, cur_node, vehicle.wade_capability)
        if stop.customer_id not in dist:   # unreachable on the live graph
            break                          # vehicle is stuck until a re-solve
        arrival = cur_time + minutes(dist[stop.customer_id])
        if arrival <= state.clock:
            stop.actual_arrival   = arrival
            stop.actual_departure = arrival + minutes(DEFAULT_SERVICE_TIME_MIN)
            deliver(); cur_node, cur_time = stop.customer_id, stop.actual_departure
        else:
            break                          # not reached yet this tick
```

Properties: deterministic, pure-CPU, adds **no persistent state** (current node
& time are derived each tick from already-visited stops). A blocked edge that
isolates a customer leaves the stop undelivered (→ drop cost) until a reroute
re-solves around it; a flooded/congested edge raises `effective_time` →
later `actual_arrival` → real lateness. Anchored at `depot.opening_time` so a
disruption-free replay reproduces the planned schedule, and disruption pushes it
strictly later.

### 3.2 Consequential injuries per event type — `make_disrupted_example`

A new dataset entry point (M-F path; the existing `make_example` is left intact
for back-compat) that, after planning + warmup, **injures the world** so each
event type poses a real choice:

| Event type | Injury | Why the actions differ |
|---|---|---|
| `traffic` | set the **critical** access edge(s) to the target customer `BLOCKED` | reroute (detour, slightly late) beats defer (drop) |
| `flooded_area` | set those edges `FLOODED` with `flood_level` above wade capability | same; reroute/reschedule beat defer |
| `demand_surge` | add a large surge to the target customer's orders | accelerate/reprioritize (serve the spike) beat passive options |
| `urgent_order` | spike + tighten the target's time window | accelerate beats reprioritize/reallocate |
| `inventory_shortage` | (already consequential) pending > depot stock | cancel/reprioritize beat defer |
| `vehicle_breakdown` | set the **committed** vehicle `BROKEN` under load pressure | reallocate/reschedule vs cancel diverge when the remaining fleet is tight |

"Critical access edge(s)" = the direct `DEPOT->Cx` edge(s) for the target
customer (including any parallel `#2`), chosen so a detour exists but is costly —
verified on the sample graph: blocking both `DEPOT->C001` edges forces the
`DEPOT->C002->C001` chain and yields `reroute/reschedule=0` vs `defer=4650`.

Injuries reuse existing simulator mutators where possible
(`disrupt_edge` for edges; direct `vehicle.status` / `customer.orders` /
`time_window` writes otherwise) so no new world-mutation surface is introduced.

### 3.3 Oracle grading wired for real outcomes

The M-F grading helper (`grade_disrupted`, alongside `grade_full`) rolls each
candidate forward with:

* **travel-time ON** — the grading sim clone has `enable_travel_time` true so the
  injury actually bites;
* **exogenous world frozen** — a grading-only `WorldSimulator.advance_only` flag
  (set on the *deepcopied* clone inside `roll_forward(..., freeze_world=True)`)
  makes `tick()` advance the clock and run **only** `_advance_vehicles` — no new
  demand, restock, shortage, or weather — so `realized_cost` measures the
  decision's effect, not unrelated order churn;
* **re-solve on resolve actions** — `roll_forward` receives
  `resolve=lambda st: reroute(st, optimizer)`, so RESOLVE_ACTIONS take effect;
* **adequate horizon** — `oracle_horizon_ticks` raised (recommended 60–72 for the
  sample world) so deliveries complete within the rollout and lateness/ drops
  materialize.

`realized_cost` itself is **unchanged** — once movement responds and demand is
frozen, the existing late-minutes + priority-weighted-drop + breach formula
separates the actions correctly.

### 3.4 Factory / settings additions

* `config/settings.py`: `enable_travel_time: bool = False`
  (env `ENABLE_TRAVEL_TIME`). No other engine selection changes.
* `roll_forward(..., freeze_world: bool = False)` — default False keeps M-A
  semantics; the M-F grading path passes True.
* `WorldSimulator.advance_only: bool = False` — default False; `tick()` checks it.

## 4. Config gating & test-suite safety

Every change is behind a default-off flag:

* `enable_travel_time=False` → `_advance_vehicles` unchanged → all movement/loop
  tests unchanged.
* `freeze_world=False` / `advance_only=False` → `tick()` unchanged → all
  simulator tests unchanged.
* `make_example` and `grade_full` are **kept** as-is; M-F adds *new*
  `make_disrupted_example` / `grade_disrupted` so M-B tests don't move.

The existing 52 SBv2 tests and the broader suite must stay green with zero
threshold edits. New behavior is covered by new tests that set the flags on.

## 5. Coverage expectation (honest)

With M-F, the factory should yield informative examples for **5–6 of 6** event
types. `inventory_shortage`, `demand_surge`, `urgent_order`, `traffic`,
`flooded_area` are confirmed to produce non-zero gaps in prototypes.
`vehicle_breakdown` is the weakest: with 3 vehicles / 4 customers the fleet
absorbs one loss, so its signal depends on load pressure; the injury applies a
surge so the remaining fleet is genuinely tight. The factory report must print
per-type `event_types` counts so a still-degenerate type is caught **before**
training (the pre-train gate in the runbook).

## 6. Downstream impact

* **M-D offline eval** (`agreement_pct` vs oracle gold) becomes meaningful across
  event types instead of measuring one class.
* **M-D/M-E datasets** must be regenerated with `ENABLE_TRAVEL_TIME=1` and the
  raised horizon; the SFT/DPO scripts and serving are unchanged.
* No change to NimAgent, factory engine selection, or the served decision schema.

## 7. Milestones (→ plan tasks)

1. `enable_travel_time` setting + travel-time `_advance_vehicles` branch (TDD:
   blocked edge ⇒ later/!delivered vs schedule-driven baseline).
2. `WorldSimulator.advance_only` freeze flag in `tick()`.
3. `roll_forward(freeze_world=...)` sets the clone's `advance_only`.
4. `make_disrupted_example` (per-type injuries) + `_critical_edges` helper.
5. `grade_disrupted` (travel-time + freeze + resolve + horizon) and an
   `iter_disrupted_examples`.
6. `gen_dataset` M-F path (`--consequential`/env) wiring + per-type coverage in
   the report.
7. End-to-end: small-seed dataset shows ≥4 event types informative.

## 8. Risks & mitigations

* **Topology-dependent edge signal.** If a target customer has a cheap detour,
  blocking one edge does nothing. Mitigation: block *all* direct depot edges to
  the target (the `_critical_edges` helper), verified on the sample graph.
* **`vehicle_breakdown` stays weak.** Mitigation: load pressure in the injury;
  if still flat at scale, document it and let the rule fallback handle that type
  (NimAgent already falls back per-event).
* **Determinism.** All injuries are seeded/deterministic; `shortest_times_from`
  is pure. Grading freezes exogenous processes, removing rollout RNG entirely.
* **Horizon cost.** Travel-time grading at horizon 72 × candidates × specs ×
  seeds is still pure CPU; the M-B run is seconds-to-minutes, not GPU work.
