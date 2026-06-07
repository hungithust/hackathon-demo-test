# M-A: Simulator Latent-Process Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Simulator's `seasonal × iid-noise` demand with a genuine latent generative process (weekly seasonality + slow trend + AR(1) autocorrelated noise + occasional regime shifts) so downstream Forecaster/Detector have real structure to recover — staying 100% synthetic, seeded-deterministic, CPU, $0.

**Architecture:** All changes live in `fleet/simulator/engine.py` (the `WorldSimulator` class + module-level pure helpers) and `config/settings.py` (new latent-process knobs). The existing per-tick demand loop in `_generate_demand` is extended multiplicatively: `expected = base × intraday_season × weekly × trend × regime × ar_noise`. Determinism is preserved by drawing every random value from the existing `self.rng`. Existing public behavior (clock advance, accumulation, injection, restock, shortage, movement) is unchanged.

**Tech Stack:** Python stdlib only (`random`, `math`, `datetime`). No new dependency. pytest.

**Spec:** `docs/superpowers/specs/2026-06-07-core-modules-deepening-design.md` §3.1 (latent-process background). Cascade (§3.3) and position interpolation (§3.4) are explicit stretch and are NOT in this plan.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `config/settings.py` | latent-process knobs (trend, weekend, AR rho/sigma, regime prob/factor/duration) | add 6 fields + env parsing |
| `fleet/simulator/engine.py` | pure helpers `_weekly_factor`, `_trend_factor`; `WorldSimulator` AR(1) + regime state and their multipliers; wire into `_generate_demand` | modify |
| `tests/test_demand_latent.py` | new tests for weekly/trend/AR/regime structure + determinism | create |
| `tests/test_config.py` | assert new settings defaults + env override | modify |

**Preserve (do NOT break):** `_seasonal_factor` (imported by `tests/test_demand.py`), `_BASE_RATE_PER_HOUR`, `_DEFAULT_BASE_RATE`, `_sample_units`, and the deterministic-per-seed contract (`tests/test_demand.py::test_demand_is_deterministic_for_same_seed`).

---

## Task 1: Latent-process settings

**Files:**
- Modify: `config/settings.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_latent_process_defaults():
    s = load_settings(env={})
    assert s.demand_trend_per_day == 0.05
    assert s.demand_weekend_factor == 0.7
    assert s.demand_ar_rho == 0.6
    assert s.demand_ar_sigma == 0.3
    assert s.regime_prob == 0.01
    assert s.regime_factor == 2.0
    assert s.regime_duration_min == 180


def test_latent_process_env_override():
    s = load_settings(env={"DEMAND_AR_RHO": "0.9", "REGIME_FACTOR": "3.5"})
    assert s.demand_ar_rho == 0.9
    assert s.regime_factor == 3.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_latent_process_defaults -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'demand_trend_per_day'`

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add these fields to the `Settings` dataclass (after `traffic_alert_factor`):

```python
    demand_trend_per_day: float = 0.05    # M-A: slow multiplicative growth per sim-day
    demand_weekend_factor: float = 0.7    # M-A: Sat/Sun demand multiplier
    demand_ar_rho: float = 0.6            # M-A: AR(1) autocorrelation of demand noise
    demand_ar_sigma: float = 0.3          # M-A: AR(1) lognormal noise scale
    regime_prob: float = 0.01             # M-A: per-customer per-tick chance to enter a promo regime
    regime_factor: float = 2.0            # M-A: demand multiplier while in a regime
    regime_duration_min: int = 180        # M-A: regime length (sim minutes)
```

In `load_settings`, add to the `Settings(...)` call:

```python
        demand_trend_per_day=float(e.get("DEMAND_TREND_PER_DAY", "0.05")),
        demand_weekend_factor=float(e.get("DEMAND_WEEKEND_FACTOR", "0.7")),
        demand_ar_rho=float(e.get("DEMAND_AR_RHO", "0.6")),
        demand_ar_sigma=float(e.get("DEMAND_AR_SIGMA", "0.3")),
        regime_prob=float(e.get("REGIME_PROB", "0.01")),
        regime_factor=float(e.get("REGIME_FACTOR", "2.0")),
        regime_duration_min=int(e.get("REGIME_DURATION_MIN", "180")),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (all config tests)

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_config.py
git commit -m "feat(sim): latent-process settings (trend, weekend, AR(1), regime)"
```

---

## Task 2: Weekly seasonality helper

**Files:**
- Modify: `fleet/simulator/engine.py`
- Test: `tests/test_demand_latent.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_demand_latent.py`:

```python
from datetime import datetime

from fleet.simulator.engine import _weekly_factor, _trend_factor


def test_weekly_factor_weekend_lower_than_weekday():
    # 2026-06-08 is a Monday; 2026-06-13 is a Saturday
    monday = datetime(2026, 6, 8)
    saturday = datetime(2026, 6, 13)
    assert _weekly_factor(monday.weekday(), 0.7) == 1.0
    assert _weekly_factor(saturday.weekday(), 0.7) == 0.7
    assert _weekly_factor(monday.weekday(), 0.7) > _weekly_factor(saturday.weekday(), 0.7)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_demand_latent.py::test_weekly_factor_weekend_lower_than_weekday -v`
Expected: FAIL — `ImportError: cannot import name '_weekly_factor'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/simulator/engine.py`, add a module-level helper just below `_seasonal_factor`:

```python
def _weekly_factor(weekday: int, weekend_factor: float) -> float:
    """Weekly seasonality: weekends (Sat=5, Sun=6) scaled by weekend_factor."""
    return weekend_factor if weekday >= 5 else 1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_demand_latent.py::test_weekly_factor_weekend_lower_than_weekday -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_demand_latent.py
git commit -m "feat(sim): weekly seasonality factor"
```

---

## Task 3: Trend helper

**Files:**
- Modify: `fleet/simulator/engine.py`
- Test: `tests/test_demand_latent.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demand_latent.py`:

```python
def test_trend_factor_grows_with_days():
    assert _trend_factor(0.0, 0.05) == 1.0
    assert _trend_factor(2.0, 0.05) == 1.1       # 1 + 0.05*2
    assert _trend_factor(10.0, 0.05) > _trend_factor(1.0, 0.05)


def test_trend_factor_never_negative():
    assert _trend_factor(100.0, -0.05) == 0.0    # clamped at 0, not negative
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_demand_latent.py::test_trend_factor_grows_with_days -v`
Expected: FAIL — `ImportError: cannot import name '_trend_factor'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/simulator/engine.py`, add below `_weekly_factor`:

```python
def _trend_factor(days_elapsed: float, trend_per_day: float) -> float:
    """Slow multiplicative trend over elapsed sim-days, floored at 0."""
    return max(0.0, 1.0 + trend_per_day * days_elapsed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_demand_latent.py -v`
Expected: PASS (weekly + trend tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_demand_latent.py
git commit -m "feat(sim): trend factor over elapsed sim-days"
```

---

## Task 4: AR(1) autocorrelated noise

**Files:**
- Modify: `fleet/simulator/engine.py` (add `import math`; init AR state; `_ar_multiplier`)
- Test: `tests/test_demand_latent.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demand_latent.py`:

```python
from config.settings import load_settings
from fleet.simulator.engine import WorldSimulator


def _ar_series(sim, cid, n):
    # underlying AR state is what we test for autocorrelation
    out = []
    for _ in range(n):
        sim._ar_multiplier(cid)
        out.append(sim._ar_state[cid])
    return out


def test_ar_noise_is_positively_autocorrelated():
    sim = WorldSimulator(load_settings(env={"DEMAND_AR_RHO": "0.9", "SEED": "7"}))
    xs = _ar_series(sim, "C1", 400)
    a = xs[:-1]
    b = xs[1:]
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    corr = cov / (va * vb)
    assert corr > 0.5            # rho=0.9 => strongly positively autocorrelated


def test_ar_multiplier_is_positive_and_deterministic():
    s1 = WorldSimulator(load_settings(env={"SEED": "42"}))
    s2 = WorldSimulator(load_settings(env={"SEED": "42"}))
    seq1 = [s1._ar_multiplier("C1") for _ in range(20)]
    seq2 = [s2._ar_multiplier("C1") for _ in range(20)]
    assert seq1 == seq2                 # same seed => identical
    assert all(m > 0 for m in seq1)     # multiplier always positive
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_demand_latent.py::test_ar_multiplier_is_positive_and_deterministic -v`
Expected: FAIL — `AttributeError: 'WorldSimulator' object has no attribute '_ar_multiplier'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/simulator/engine.py`:

(a) At the top, change `import random` to also import math:

```python
import math
import random
```

(b) In `WorldSimulator.__init__`, after `self._restock_batch = None`, add:

```python
        self._ar_state: Dict[str, float] = {}   # M-A: per-customer AR(1) state
        self._regime_until: Dict[str, "datetime"] = {}  # M-A: regime end clock
```

(c) Add a method on `WorldSimulator` (place it just above `_generate_demand`):

```python
    def _ar_multiplier(self, cid: str) -> float:
        """AR(1) autocorrelated, mean~1, strictly-positive demand multiplier.

        a_t = rho*a_{t-1} + sqrt(1-rho^2)*eps;  multiplier = exp(sigma*a_t - sigma^2/2).
        The lognormal mean-correction keeps the long-run mean ~= 1.0."""
        rho = self.settings.demand_ar_rho
        sigma = self.settings.demand_ar_sigma
        prev = self._ar_state.get(cid, 0.0)
        eps = self.rng.gauss(0.0, 1.0)
        a = rho * prev + math.sqrt(max(0.0, 1.0 - rho * rho)) * eps
        self._ar_state[cid] = a
        return math.exp(sigma * a - 0.5 * sigma * sigma)
```

Note: `datetime` is already imported indirectly? It is NOT — only `timedelta` is imported. The `_regime_until` annotation uses a string `"datetime"`, so no import is needed for the annotation. Do not add a runtime `datetime` use here.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_demand_latent.py -v`
Expected: PASS (weekly + trend + AR tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_demand_latent.py
git commit -m "feat(sim): AR(1) autocorrelated demand noise"
```

---

## Task 5: Regime shifts (promotions)

**Files:**
- Modify: `fleet/simulator/engine.py` (`_regime_multiplier`)
- Test: `tests/test_demand_latent.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demand_latent.py`:

```python
from fleet.scenarios import build_sample_state


def test_regime_starts_when_prob_one():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"REGIME_PROB": "1.0", "REGIME_FACTOR": "2.0"}))
    m = sim._regime_multiplier("C1", s.clock)
    assert m == 2.0                       # forced into regime => factor applied


def test_no_regime_when_prob_zero():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"REGIME_PROB": "0.0"}))
    assert sim._regime_multiplier("C1", s.clock) == 1.0


def test_regime_is_deterministic():
    s = build_sample_state()
    s1 = WorldSimulator(load_settings(env={"SEED": "42", "REGIME_PROB": "0.3"}))
    s2 = WorldSimulator(load_settings(env={"SEED": "42", "REGIME_PROB": "0.3"}))
    clk = s.clock
    seq1, seq2 = [], []
    for _ in range(30):
        seq1.append(s1._regime_multiplier("C1", clk))
        seq2.append(s2._regime_multiplier("C1", clk))
        clk += timedelta(minutes=30)
    assert seq1 == seq2
```

Add `from datetime import timedelta` to the imports at the top of `tests/test_demand_latent.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_demand_latent.py::test_regime_starts_when_prob_one -v`
Expected: FAIL — `AttributeError: 'WorldSimulator' object has no attribute '_regime_multiplier'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/simulator/engine.py`, add below `_ar_multiplier`:

```python
    def _regime_multiplier(self, cid: str, clock) -> float:
        """Occasional promotion regime: with prob `regime_prob` per call a customer
        enters a `regime_factor` demand regime lasting `regime_duration_min`."""
        until = self._regime_until.get(cid)
        if until is not None and clock < until:
            return self.settings.regime_factor
        # not currently in a regime: maybe start one
        if self.rng.random() < self.settings.regime_prob:
            self._regime_until[cid] = clock + timedelta(
                minutes=self.settings.regime_duration_min)
            return self.settings.regime_factor
        return 1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_demand_latent.py -v`
Expected: PASS (weekly + trend + AR + regime tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_demand_latent.py
git commit -m "feat(sim): occasional promotion regime shifts"
```

---

## Task 6: Wire the latent process into `_generate_demand`

**Files:**
- Modify: `fleet/simulator/engine.py` (`tick` captures start clock; `_generate_demand` composes the factors)
- Test: `tests/test_demand_latent.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demand_latent.py` (this is the end-to-end structure test):

```python
def _run_total_demand(env, n_ticks):
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env=env))
    totals = []
    prev = 0
    for _ in range(n_ticks):
        sim.tick(s)
        now = s.total_orders_pending()
        totals.append(now - prev)   # demand added this tick (orders only grow until delivered)
        prev = now
    return s, totals


def test_demand_uses_regime_when_forced():
    # With regime forced on and a big factor, total demand exceeds a no-regime baseline.
    base_s, _ = _run_total_demand({"SEED": "1", "REGIME_PROB": "0.0"}, 40)
    promo_s, _ = _run_total_demand(
        {"SEED": "1", "REGIME_PROB": "1.0", "REGIME_FACTOR": "3.0"}, 40)
    assert promo_s.total_orders_pending() > base_s.total_orders_pending()


def test_generate_demand_still_deterministic():
    s1, _ = _run_total_demand({"SEED": "42"}, 20)
    s2, _ = _run_total_demand({"SEED": "42"}, 20)
    o1 = {cid: dict(c.orders) for cid, c in s1.customers.items()}
    o2 = {cid: dict(c.orders) for cid, c in s2.customers.items()}
    assert o1 == o2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_demand_latent.py::test_demand_uses_regime_when_forced -v`
Expected: FAIL — regime/weekly/trend not yet composed into `_generate_demand`, so the promo and baseline totals are equal (assert fails).

- [ ] **Step 3: Write minimal implementation**

(a) In `WorldSimulator.__init__`, add (next to `self._ar_state`):

```python
        self._start_clock = None          # M-A: captured on first tick for trend
```

(b) In `tick`, capture the start clock right where `_restock_batch` is snapshotted:

```python
        if self._restock_batch is None:
            self._restock_batch = dict(state.depot.inventory)
        if self._start_clock is None:
            self._start_clock = state.clock
```

(c) Replace the body of `_generate_demand` with the composed version:

```python
    def _generate_demand(self, state: WorldState) -> None:
        if not state.depot.inventory:
            return
        skus = sorted(state.depot.inventory.keys())
        hours_per_tick = self.settings.tick_minutes / 60.0
        intraday = _seasonal_factor(state.clock.hour)
        weekly = _weekly_factor(state.clock.weekday(),
                                self.settings.demand_weekend_factor)
        days_elapsed = (
            (state.clock - self._start_clock).total_seconds() / 86400.0
            if self._start_clock is not None else 0.0)
        trend = _trend_factor(days_elapsed, self.settings.demand_trend_per_day)
        for c in state.customers.values():
            base = _BASE_RATE_PER_HOUR.get(c.type, _DEFAULT_BASE_RATE)
            expected = base * hours_per_tick * intraday * weekly * trend
            expected *= self._regime_multiplier(c.id, state.clock)
            expected *= self._ar_multiplier(c.id)
            units = self._sample_units(expected)
            if units <= 0:
                continue
            sku = self.rng.choice(skus)
            c.orders[sku] = c.orders.get(sku, 0) + units
```

Note the iteration order is `state.customers.values()` (unchanged) and the per-customer key is `c.id` — make sure `CustomerProfile` exposes `.id` (it does: `state.py` line 110). The old iid `self.rng.uniform(1-noise, 1+noise)` is intentionally removed; `demand_noise` is now superseded by the AR(1) noise (leave the setting in place for backward-compat / other callers, but it is no longer read here).

- [ ] **Step 4: Run the new tests, then the demand suite**

Run: `pytest tests/test_demand_latent.py tests/test_demand.py -v`
Expected: PASS — including the preserved `test_demand.py` accumulation/determinism/seasonal tests.

- [ ] **Step 5: Run the FULL suite (guard against downstream drift)**

Run: `pytest -q`
Expected: PASS. If `test_loop.py` / `test_movement.py` / `test_shortage.py` regress, it is because demand magnitudes shifted — these tests assert structural facts (filtered by injected `event_id`, monotonic counts), so fix the test thresholds **test-side only** (do NOT weaken the latent process). Record any such adjustment in the commit message.

- [ ] **Step 6: Headless smoke**

Run: `python -m fleet.loop`
Expected: runs clean to completion (no traceback); demand still accumulates and deliveries occur.

- [ ] **Step 7: Commit**

```bash
git add fleet/simulator/engine.py tests/test_demand_latent.py
git commit -m "feat(sim): compose latent process (intraday x weekly x trend x regime x AR) into demand"
```

---

## Self-Review

**Spec coverage (§3.1):** intraday seasonality (kept `_seasonal_factor`), weekly seasonality (Task 2), trend (Task 3), AR(1) autocorrelated noise (Task 4), regime shifts (Task 5), all composed (Task 6). Traffic = rush-hour × weather is **deferred**: this plan covers the **demand** half of §3.1; the traffic/weather process is a follow-on task within M-A (call it M-A2) to keep this plan shippable and reviewable — flagged here so it is not forgotten. Injection overlay (§3.2) is unchanged and still works (no code path touched). Cascade (§3.3) and interpolation (§3.4) are spec-marked stretch, out of scope.

**Placeholder scan:** none — every step has concrete code and commands.

**Type consistency:** `_weekly_factor(weekday: int, weekend_factor: float)`, `_trend_factor(days_elapsed: float, trend_per_day: float)`, `_ar_multiplier(cid)`, `_regime_multiplier(cid, clock)`, state dicts `_ar_state`/`_regime_until`/`_start_clock` — names are identical across Tasks 4–6 and the wiring in Task 6. `c.id` confirmed against `state.py:110`.

**Determinism:** every stochastic draw (`rng.gauss`, `rng.random`, `rng.choice`, `_sample_units`) comes from the single `self.rng` seeded in `__init__`; Tasks 4–6 each assert same-seed reproducibility.

---

## Follow-on (next plans in this milestone series)

- **M-A2** (small): traffic = rush-hour multiplier × autocorrelated weather process driving probabilistic flooding on flood-prone edges (completes §3.1).
- **M-B**: Holt-Winters forecaster + prediction intervals (consumes this demand structure).
- **M-C**: forecast-residual + CUSUM detectors.
- **M-D**: scoring-policy DecisionEngine.
