# Core Modules Deepening — making the 6-module spine genuinely intelligent

> Version: 1.0 · Date: 2026-06-07
> Status: design approved, awaiting spec review
> Scope: Deepen the **base** decision pipeline (Simulator → Forecaster → Detector →
> DecisionEngine) beyond the M0–M7 walking-skeleton level. Complements — does not replace —
> the three competition-upgrade specs (Sovereign Brain, cuOpt-at-scale, Demo-polish).
> Context: NVIDIA Open Hackathon 2026 (Viettel × NVIDIA). Judging weights: NVIDIA-stack
> usage, business impact/demo, technical novelty.

---

## 0. One sentence

Turn the four most skeletal core modules — the ones the codebase's own "known limitations"
flag (flat EWMA, threshold-only / cross-sectional detection, naive 1-to-1 rule decisions,
schedule-only movement) — into a coherent, principled pipeline, **entirely on synthetic,
deterministic, $0, CPU-only data**, where each module's intelligence is real because the
Simulator now generates real latent structure for the others to recover.

## 1. Guiding principle (locked, drives everything)

**A Detector/Forecaster is only as intelligent as the structure the Simulator actually puts
in the data.** Because the world is 100% synthetic, if the Simulator emits
`demand = level × season + white noise`, any "smart" Forecaster/Detector is merely
re-discovering the noise knob we turned — theatre, not capability, and a sharp judge sees it.

Therefore: the Simulator must generate **genuine latent structure** (trend, multi-period
seasonality, autocorrelation, regime shifts, correlated shocks, cascading events) **whose
generating parameters the downstream modules never see.** Only then are forecasting and
detection real problems. Everything stays pure Python, CPU, seeded-deterministic, $0 — this
is principled data *generation*, not an external dataset.

This principle is the reason the four modules are designed **together**, in pipeline order.

## 2. Non-goals

- NOT introducing any real-world dataset, map, or paid data source (decision locked: 100%
  synthetic). No OpenStreetMap, no Kaggle, no company data.
- NOT changing the 6 `Protocol` interfaces, the loop's event-lifecycle/dedup contract, the
  approval gate, the `Decision`/`Event`/`WorldState` schema, or the factory's
  "safe-fallback default" philosophy. All upgrades slot behind existing interfaces.
- NOT replacing the existing defaults destructively: `EwmaForecaster` and the rule
  `RuleBasedEngine` name stay valid; richer impls are added/selected by config.
- NOT requiring a GPU, an API key, or network access for the test suite (same discipline as
  the rest of the codebase: pure functions, injected transport where relevant).
- NOT building Prophet, learned multivariate detectors, or counterfactual lookahead as core
  scope — they are named stretch only.

## 3. Module 1 — Simulator (the source of all signal)

**Current:** schedule-driven vehicle movement (no position interpolation); demand =
seasonal + noise; periodic restock; INVENTORY_SHORTAGE lifecycle.

**Chosen approach: Hybrid (latent-process background + scripted injection overlay).**

### 3.1 Latent-process background (`fleet/simulator/`, pure, seeded)
Model each customer's demand as a real generative process, parameters hidden from downstream:
- `demand_t = base_level + trend·t + seasonality(daily + weekly, Fourier terms)
  + AR(1) noise + occasional regime_shift (promotion / holiday level-jump)`.
- **Traffic** = rush-hour multiplier (bell-shaped around morning/evening peaks) × a weather
  process (rain probability with temporal autocorrelation → probabilistic flooding on
  flood-prone edges, reusing existing `EdgeStatus.FLOODED` + `flood_level`).
- All parameters seeded → fully deterministic and reproducible; bounded by reference-able
  ranges (HCM peak hours, retail seasonal amplitude) so they are defensible to judges.

### 3.2 Scripted injection overlay (reuse existing)
The presenter-facing `inject_*` / `disrupt_edge` / `inject_event` hooks stay as the on-cue
control layer **on top of** the latent background. Background = real statistics for
Forecaster/Detector; injection = stage control for the live demo. No conflict: injection is
a deliberate override.

### 3.3 Cascading events (stretch-eligible but recommended)
A disruption propagates causally: `flood edge → traffic ↑ on detour edges → delays →
SLA risk`. Gives the Detector a real cause→effect chain to recover (see §5.2). Effort M.

### 3.4 Position interpolation (stretch only — YAGNI unless the map is built)
Move vehicles continuously along an edge by `t / effective_time` for a smoother UI map.
Effort S. Deferred unless the Demo-polish map materializes.

**Feasibility:** pure Python / CPU / seeded / $0. Risk = calibrating the latent parameters to
"look real"; mitigated by reference-bounded ranges + a sanity test that plots one generated
series and asserts the intended components are present.

## 4. Module 2 — Forecaster (recover the structure)

**Current:** `EwmaForecaster` — single exponential smoothing, flat-horizon forecast. Drifts
whenever trend/seasonality exists — which §3 now deliberately introduces.

**Chosen approach: Holt-Winters (triple exponential smoothing) + prediction intervals.**

### 4.1 Holt-Winters forecaster (`fleet/forecast/`)
Extend the existing EWMA family to **level + trend + seasonality** — structurally matching
what §3.1 generates ("we forecast exactly the components the world actually has"). Either
hand-rolled (~40 lines, no new dep) or via `statsmodels` (CPU, deterministic). $0. Effort M.

### 4.2 Prediction intervals
Return `{forecast, lower, upper}` from residual variance. This gives the Detector a
**context-dependent band** (wide at rush hour, narrow at night) instead of a hard constant —
the key Forecaster↔Detector coupling. Effort S.

### 4.3 Proactive signal
When the forecast exceeds projected inventory, emit a signal the DecisionEngine can act on
(pre-order / pre-position) — consumed in §6. Forecaster side is small (Effort S).

**Defaults / fallback:** `EwmaForecaster` remains the $0 default and fallback (existing
contract unchanged); Holt-Winters is selected via `FORECASTER_ENGINE`. `prophet` stays a
named-but-unimplemented future slot.

**Feasibility:** pure CPU / deterministic / $0. Risk = short sim series → noisy seasonal
estimate; mitigated by a warm-up of a few cycles before trusting the forecast, and tests on
a series with known components.

## 5. Module 3 — Detector (find what shouldn't be there)

**Current:** `RuleDetector` (edge/vehicle thresholds) + `ZScoreDetector` (cross-sectional
order-volume z-score). No temporal dimension.

**Design rule (locked): separate the two signal classes.**
- **Ground-truth state** (edge BLOCKED/FLOODED, vehicle BROKEN) is *fact*, not statistics →
  rules are correct. Keep `RuleDetector` as-is; do NOT "ML-ify" the deterministic.
- **Statistical anomaly** (demand / traffic deviating from expectation) is where intelligence
  is added.

### 5.1 Forecast-residual detector (core, `fleet/detection/`)
Compare actual vs the Holt-Winters **prediction band**: above upper → `DEMAND_SURGE`, below
lower → demand-drop. Dynamic, context-aware threshold; adds the temporal dimension the
cross-sectional z-score lacks. Effort M.

### 5.2 CUSUM / control-chart detector (complement)
Detect **slow drift / regime shifts** (the level-jumps §3.1 injects) that a single-tick
threshold misses because each tick is individually sub-threshold but the accumulation is not.
~30 lines, no new dep. Effort M. High novelty.

### 5.3 Severity from magnitude
Map deviation size (sigmas / band-exceedance) to `EventSeverity` LOW→CRITICAL bands instead
of a hard-coded level. Effort S.

### 5.4 Cascade correlation (stretch)
Group anomalies sharing one causal chain (§3.3) into a single root-cause Event + its
consequences, rather than spamming separate events. Effort M. Earns the "reasons about
cause" narrative.

**Selection:** layered — `RuleDetector` (ground-truth, kept) + `ForecastResidualDetector`
(§5.1) + `CusumDetector` (§5.2), chosen via `DETECTOR_ENGINE` (or run stacked).

**Feasibility:** pure CPU / $0 / no new dep. Risk = multiple detectors → noise/duplication;
mitigated by the existing `DET_*` lifecycle + loop dedup, and severity-gating (only surface
events above a severity floor).

## 6. Module 4 — DecisionEngine (the highest-leverage upgrade)

**Current:** `RuleBasedEngine` — a 1-to-1 event→action map, no trade-off reasoning.

**Why highest leverage:** a principled rule engine improves *three* things at once — the
live demo (explainable cards), the **Sovereign Brain** (a better deterministic *teacher* and
a better $0 *fallback* than a naive map), and the with/without-agent KPI delta — at $0 and
no new dependency.

**Chosen approach: scoring policy + proactive decisions + structured reasoning.**

### 6.1 Scoring policy (`fleet/agent/`)
For each event, enumerate candidate `DecisionAction`s (reroute / reschedule / reprioritize /
reallocate / defer / cancel / accelerate), **score each** by a context cost function —
SLA-breach risk, added delay, travel-time/fuel proxy, priority-weighted dropped orders — and
pick the best. Replaces the 1-to-1 map with genuine trade-off evaluation. Deterministic /
CPU / $0. Effort M.

### 6.2 Proactive decisions
Consume the Forecaster proactive signal (§4.3): forecast exceeds projected stock → propose
pre-order / pre-position **before** the shortage, not only reactively. Matches problem.txt's
"self-reason & propose" goal. Effort S–M.

### 6.3 Structured reasoning
Persist the scored-alternatives table (not just a prose string) → richer
"explainable" decision cards **and** higher-quality teacher labels for the NIM. Effort S.

**Stretch (named, out of core scope):** counterfactual lookahead (§ "Cách C") — simulate each
candidate a few ticks and pick by simulated KPI; principled but per-tick-expensive (Effort L).

**Interfaces unchanged:** this becomes the new `RuleBasedEngine`; `ClaudeAgent` / `NimAgent`
stay behind the same `DecisionEngine` interface and now have a *credible* deterministic
baseline to be compared against and to fall back to.

**Feasibility:** pure CPU / $0 / no new dep. Risk = a multi-weight cost function that is hard
to "get right"; mitigated by a few clearly-ordered weights (SLA ≫ fuel) and tests on
scenarios with a known expected action.

## 7. Feasibility summary (the explicit requirement)

| Unit | Data | Compute | API cost | New dep | Effort |
|---|---|---|---|---|---|
| Simulator latent-process (§3.1) | synthetic, seeded | CPU, pure | $0 | none | M |
| Simulator injection overlay (§3.2) | reuses existing | CPU, pure | $0 | none | S (exists) |
| Simulator cascade (§3.3) | synthetic | CPU, pure | $0 | none | M (stretch) |
| Position interpolation (§3.4) | synthetic | CPU, pure | $0 | none | S (stretch) |
| Holt-Winters forecaster (§4.1) | synthetic | CPU, pure | $0 | statsmodels *or none* (hand-roll) | M |
| Prediction intervals (§4.2) | synthetic | CPU, pure | $0 | none | S |
| Forecast-residual detector (§5.1) | synthetic | CPU, pure | $0 | none | M |
| CUSUM detector (§5.2) | synthetic | CPU, pure | $0 | none | M |
| Severity-from-magnitude (§5.3) | synthetic | CPU, pure | $0 | none | S |
| Cascade correlation (§5.4) | synthetic | CPU, pure | $0 | none | M (stretch) |
| Scoring policy engine (§6.1) | synthetic | CPU, pure | $0 | none | M |
| Proactive decisions (§6.2) | synthetic | CPU, pure | $0 | none | S–M |
| Structured reasoning (§6.3) | synthetic | CPU, pure | $0 | none | S |

**Total external resource requirement: none.** No dataset, no GPU, no API budget. The only
optional dependency is `statsmodels`, avoidable by hand-rolling Holt-Winters. Everything is
deterministic and unit-testable headless — same discipline as the existing codebase.

## 8. Cross-module synergies (why "together")

- **Simulator → Forecaster:** latent structure (§3.1) is what makes Holt-Winters (§4.1) more
  than EWMA — a real signal to recover.
- **Forecaster → Detector:** prediction intervals (§4.2) become the Detector's dynamic
  threshold (§5.1) — no hard constants.
- **Simulator → Detector:** regime shifts (§3.1) and cascades (§3.3) are exactly what CUSUM
  (§5.2) and cascade-correlation (§5.4) recover.
- **Forecaster → DecisionEngine:** proactive signal (§4.3) enables proactive decisions (§6.2).
- **DecisionEngine → competition specs:** the scoring engine (§6) is a *better teacher* and
  *better $0 fallback* for Sovereign Brain, and a *credible baseline* for the Demo-polish
  with/without-agent KPI delta. Structured reasoning (§6.3) feeds the explainable cards.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Latent params "don't look real" | reference-bounded ranges; sanity-plot test asserting components |
| Smart modules just recover our own knobs (theatre) | downstream never sees generating params; held-out evaluation framing |
| Short sim series → noisy seasonality | warm-up cycles before trusting forecast; tests on known-component series |
| Detector noise / duplicate events | reuse `DET_*` lifecycle + loop dedup; severity-gating floor |
| Scoring weights hard to tune | few clearly-ordered weights (SLA ≫ fuel); tests with known expected action |
| Scope creep (Prophet, learned MV, lookahead, map) | all explicitly named stretch in §2/§3.4/§5.4/§6 |
| Time pressure | each module ships independently; stretch items are severable |

## 10. Definition of done (milestones, independently demoable)

1. **M-A — Simulator latent-process:** demand = level+trend+seasonality+AR(1)+regime;
   traffic = rush-hour × weather; seeded/deterministic; sanity-plot test. Injection overlay
   still works. (Cascade §3.3 / interpolation §3.4 are stretch within this milestone.)
2. **M-B — Forecaster:** Holt-Winters + prediction intervals behind `FORECASTER_ENGINE`;
   EWMA stays default/fallback; tested on a known-component series.
3. **M-C — Detector:** forecast-residual detector + CUSUM + severity-from-magnitude, layered
   with the kept `RuleDetector`; selected via `DETECTOR_ENGINE`. (Cascade-correlation stretch.)
4. **M-D — DecisionEngine:** scoring policy replaces the 1-to-1 map; proactive decisions from
   the Forecaster signal; structured reasoning persisted. `ClaudeAgent`/`NimAgent` unchanged
   behind the interface. (Lookahead stretch.)

Each milestone = its own plan in the plan-series, executed in a separate session
(see split-execution-planning-sessions).
