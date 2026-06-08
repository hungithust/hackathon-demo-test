# Demo Polish — make the autonomous loop sell itself

> Version: 1.0 · Date: 2026-06-05
> Status: design approved, awaiting spec review
> Scope: ONE of three competition-upgrade specs (others: Sovereign Brain, cuOpt at scale).
> Context: NVIDIA Open Hackathon 2026 (Viettel × NVIDIA). Judging weights: NVIDIA-stack
> usage, business impact/demo, technical novelty. This spec targets the **business/demo** axis.

---

## 0. One sentence

Turn the working-but-utilitarian Streamlit dashboard into a persuasive demo of the autonomous
loop — **detect → reason → decide → (approve) → dispatch** — by adding three things judges
respond to: a **with-agent-vs-without KPI delta**, **explainable decision cards**, and
**scenario-injection buttons** for a scripted, repeatable live demo.

## 1. Why this is in scope

A decent system shown flatly loses to a good system shown well. The controller already exposes
a clean JSON `snapshot()` and reuses `run_loop`/`reroute`, so this is almost entirely additive:
new snapshot fields + a richer `app.py` + one counterfactual runner. High payoff on the
business/demo axis for low risk.

## 2. Scope: in / out

**In (locked):**
1. With-agent vs without-agent **KPI delta** (counterfactual baseline).
2. **Explainable decision cards** (reasoning + impact + which engine).
3. **Scenario-injection buttons** (the 4 disruption classes on cue).

**Out (explicitly deferred — stretch only if everything else lands early):**
live event timeline, pydeck network/route map, KPI-over-time charts. Listed so the executor
doesn't pull them in.

## 3. Honest framing (must stay in the pitch)

KPI deltas are only as real as the simulator. Present them as **"simulated impact"** — the demo
shows the *mechanism* of value (the agent prevents late deliveries / re-optimizes under
disruption), not a validated production number. Say so out loud; it reads as credible, not weak.

## 4. Components

### 4.1 Explainable decision cards (lowest effort, high signal)
- **Controller:** extend `snapshot()["pending_decisions"]` (and a parallel recent-decisions list)
  with `reasoning` (`Decision.reasoning`) and `engine` (`Decision.engine.value` — surfaces
  Claude vs self-hosted NIM vs rule-based, tying into the Sovereign Brain story).
- **app.py:** render each decision as a card — action, target/event, **reasoning text**, impact
  estimate (added delay), engine badge, and Approve/Reject. Replaces the current flat line.
- No engine changes; the data already exists on `Decision`.

### 4.2 Scenario-injection buttons (presenter control)
- **Controller:** add explicit injection methods, each a small, deterministic state mutation that
  the next `step()`'s detector turns into an event → decision:
  - `inject_flood(edge_id?)` / `inject_blocked(edge_id?)` → wraps `WorldSimulator.disrupt_edge`
    (transport disruption).
  - `inject_demand_surge(customer_id?, factor)` → bumps a customer's pending orders.
  - `inject_breakdown(vehicle_id?)` → sets a vehicle `VehicleStatus.BROKEN`.
  - `inject_supply_shortage()` → drives depot stock down to trigger the existing
    `INVENTORY_SHORTAGE` lifecycle.
  Each picks a sensible default target when the arg is omitted, and is a no-op-safe if nothing
  matches (so the demo never errors).
- **app.py:** a row of four buttons (one per disruption class). The presenter triggers a class,
  steps once, and the detect→decide→dispatch loop plays out live and repeatably.

### 4.3 With-agent vs without-agent KPI delta (the business proof)
- **Controller:** `run_comparison(n_ticks, seed) -> dict`. Build **two** worlds from the *same
  seed* (identical demand/events): one **agent-on** (decisions applied automatically — normal
  policy plus auto-approve of escalated decisions, mirroring `run_loop` + human approve), one
  **agent-off** (no decisions applied — pure baseline). Step both `n_ticks`; compute KPIs from
  final state and return `{agent_on, agent_off, delta}`.
- **KPI helper** (`fleet/ui/kpis.py`, pure): compute from state — **on-time deliveries**
  (actual_arrival ≤ time-window end), **late count + total delay minutes**, **unserved/dropped
  orders**, and a **cost proxy** (total route/travel time). Reuses the existing
  `actual_arrival` / `planned_arrival` / 2-phase late-delivery fields.
- **app.py:** a KPI strip showing agent-on vs agent-off side by side with the delta
  highlighted ("agent prevented N late deliveries / cut delay by X min / saved Y% travel time").
  Determinism (shared seed) is what makes the comparison fair and reproducible on stage.

## 5. Components & boundaries

| Unit | Purpose | Deps | Runtime path |
|---|---|---|---|
| `fleet/ui/kpis.py` | pure KPI computation from `WorldState` | state only | no (pure, testable) |
| `fleet/ui/controller.py` (extend) | reasoning/engine in snapshot; injection methods; `run_comparison` | existing controller deps | no (headless, testable) |
| `fleet/ui/app.py` (rewrite layout) | cards, injection buttons, KPI strip | streamlit only | UI only |

`streamlit` stays imported **only** in `app.py`; the controller + KPI helper are fully
unit-testable headless, same discipline as today. No engine/loop/solver changes.

## 6. Evaluation / acceptance
- `kpis.py` unit-tested against hand-built states (known on-time/late/dropped counts).
- `run_comparison` unit-tested: agent-on yields ≥ as-good KPIs as agent-off on a seed where the
  agent demonstrably helps (e.g. an injected flood it reroutes around).
- Injection methods unit-tested: each produces the expected event on the next `step()`.
- `app.py` manual-smoke only (`streamlit run`), as today — plus a headless `AppTest` asserting
  the KPI strip, a decision card with reasoning, and the four injection buttons render.

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| KPI delta near zero on a calm seed | inject a disruption in the comparison seed so the agent has something to fix; pick a seed where the gap is clear; report honestly |
| Over-claiming production impact | label everything "simulated impact" (§3) |
| Counterfactual drift (worlds diverge for the wrong reason) | same seed + only difference = whether decisions are applied; assert determinism in tests |
| Scope creep into map/timeline/charts | §2 marks them out; executor defers |

## 8. Definition of done (milestones, independently demoable)

1. **M-A:** decision cards with reasoning + engine badge (snapshot fields + app card layout).
2. **M-B:** four scenario-injection buttons wired through the controller; each plays out live.
3. **M-C:** `kpis.py` + `run_comparison` + KPI strip showing agent-on vs agent-off delta.

Each milestone = its own plan in the plan-series, executed in a separate session.
