# M-B: Holt-Winters Forecaster + Prediction Intervals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a hand-rolled Holt-Winters (triple exponential smoothing: level + trend + additive seasonality) forecaster that returns a point forecast **plus prediction intervals**, structurally matching the demand process M-A/M-A2 now generate — selected via `FORECASTER_ENGINE=holt`, with `EwmaForecaster` remaining the default/fallback.

**Architecture:** New `fleet/forecast/holt_winters.py` with module-level pure helpers (`_mean`, `_std`, `_smooth`) and a `HoltWintersForecaster` class implementing the existing `Forecaster` protocol (`forecast(history, horizon_h) -> dict`). No new dependency — the recurrences are ~50 lines of stdlib. `config/settings.py` gains smoothing/season knobs; `fleet/factory.py` selects Holt-Winters when requested, else keeps EWMA. The returned dict keeps the `forecast` key (common contract) and adds `lower`/`upper`/`trend`/`sigma`. Graceful degradation: empty history → zeros; fewer than two full seasons → a flat warm-up forecast with a wide interval (the "warm-up before trusting the forecast" the spec calls for).

**Tech Stack:** Python stdlib only (`math`). No statsmodels, no numpy. pytest.

**Spec:** `docs/superpowers/specs/2026-06-07-core-modules-deepening-design.md` §4.1 (Holt-Winters), §4.2 (prediction intervals). The proactive signal (§4.3) is consumed in M-D, not here.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `config/settings.py` | `forecaster_engine` value `holt`; `hw_alpha/hw_beta/hw_gamma`, `season_length`, `pi_z` | add 5 fields + env parsing |
| `fleet/forecast/holt_winters.py` | `HoltWintersForecaster` + pure helpers | create |
| `fleet/factory.py` | select Holt-Winters when `forecaster_engine == "holt"`, else EWMA | modify 1 line + import |
| `tests/test_holt_winters.py` | unit tests: empty, warm-up, trend, seasonality, intervals, protocol | create |
| `tests/test_config.py` | new settings defaults + env override | modify |
| `tests/test_factory.py` | factory returns Holt-Winters on `FORECASTER_ENGINE=holt`, EWMA by default | modify |

**Preserve:** `EwmaForecaster` and all its tests are untouched; it stays the default. The `Forecaster` protocol signature is unchanged.

---

## Task 1: Holt-Winters settings

**Files:**
- Modify: `config/settings.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_holt_winters_defaults():
    s = load_settings(env={})
    assert s.hw_alpha == 0.3
    assert s.hw_beta == 0.1
    assert s.hw_gamma == 0.1
    assert s.season_length == 24
    assert s.pi_z == 1.96


def test_holt_winters_env_override():
    s = load_settings(env={"FORECASTER_ENGINE": "holt", "SEASON_LENGTH": "12"})
    assert s.forecaster_engine == "holt"
    assert s.season_length == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_holt_winters_defaults -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'hw_alpha'`

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add to the `Settings` dataclass (after the M-A2 weather fields):

```python
    hw_alpha: float = 0.3                 # M-B: Holt-Winters level smoothing
    hw_beta: float = 0.1                  # M-B: Holt-Winters trend smoothing
    hw_gamma: float = 0.1                 # M-B: Holt-Winters seasonal smoothing
    season_length: int = 24               # M-B: seasonal period (in history steps)
    pi_z: float = 1.96                    # M-B: prediction-interval z (1.96 = ~95%)
```

In `load_settings`, add to the `Settings(...)` call:

```python
        hw_alpha=float(e.get("HW_ALPHA", "0.3")),
        hw_beta=float(e.get("HW_BETA", "0.1")),
        hw_gamma=float(e.get("HW_GAMMA", "0.1")),
        season_length=int(e.get("SEASON_LENGTH", "24")),
        pi_z=float(e.get("PI_Z", "1.96")),
```

(`forecaster_engine` already exists and parses `FORECASTER_ENGINE`; `holt` is just a new allowed value.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_config.py
git commit -m "feat(forecast): Holt-Winters settings (alpha/beta/gamma, season_length, pi_z)"
```

---

## Task 2: Forecaster skeleton — empty & warm-up paths

**Files:**
- Create: `fleet/forecast/holt_winters.py`
- Test: `tests/test_holt_winters.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_holt_winters.py`:

```python
from fleet.contracts.interfaces import Forecaster
from fleet.forecast.holt_winters import HoltWintersForecaster
from config.settings import load_settings


def _f(env=None):
    return HoltWintersForecaster(load_settings(env=env or {}))


def test_conforms_to_protocol():
    assert isinstance(HoltWintersForecaster(), Forecaster)


def test_empty_history_is_zero_forecast():
    out = _f().forecast([], horizon_h=3)
    assert out["forecast"] == [0.0, 0.0, 0.0]
    assert out["lower"] == [0.0, 0.0, 0.0]
    assert out["upper"] == [0.0, 0.0, 0.0]


def test_short_history_warms_up_flat_with_interval():
    # season_length=3 needs >=6 points; give 4 -> warm-up flat mean
    out = _f({"SEASON_LENGTH": "3"}).forecast([10.0, 12.0, 8.0, 10.0], horizon_h=2)
    assert out.get("warmup") is True
    assert out["forecast"] == [10.0, 10.0]            # flat at the mean
    assert out["lower"][0] <= out["forecast"][0] <= out["upper"][0]


def test_nonpositive_horizon_returns_empty_forecast():
    out = _f().forecast([1.0, 2.0, 3.0], horizon_h=0)
    assert out["forecast"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_holt_winters.py::test_empty_history_is_zero_forecast -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.forecast.holt_winters'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/forecast/holt_winters.py`:

```python
"""Holt-Winters (triple exponential smoothing) forecaster with prediction
intervals (M-B). Additive seasonality. Pure, deterministic, stdlib only.

Returns {level, trend, sigma, forecast, lower, upper}. Degrades gracefully:
empty history -> zeros; < 2 full seasons -> flat warm-up forecast (wide
interval) so callers don't trust an under-determined seasonal fit. EWMA stays
the default Forecaster; Holt-Winters is selected via FORECASTER_ENGINE=holt."""

import math
from typing import Dict, List


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _smooth(raw, default: float) -> float:
    """Clamp a smoothing coefficient into (0, 1]."""
    v = float(raw if raw is not None else default)
    return min(1.0, max(1e-6, v))


class HoltWintersForecaster:
    def __init__(self, settings=None):
        self.alpha = _smooth(getattr(settings, "hw_alpha", 0.3), 0.3)
        self.beta = _smooth(getattr(settings, "hw_beta", 0.1), 0.1)
        self.gamma = _smooth(getattr(settings, "hw_gamma", 0.1), 0.1)
        self.m = max(1, int(getattr(settings, "season_length", 24) or 24))
        self.z = float(getattr(settings, "pi_z", 1.96) or 1.96)

    def forecast(self, history: list, horizon_h: int) -> Dict:
        h = max(0, int(horizon_h))
        y = [float(v) for v in history]
        n = len(y)
        if n == 0:
            return {"level": 0.0, "trend": 0.0, "sigma": 0.0,
                    "forecast": [0.0] * h, "lower": [0.0] * h, "upper": [0.0] * h}
        m = self.m
        if n < 2 * m:
            level = _mean(y)
            band = self.z * _std(y)
            return {"level": level, "trend": 0.0, "sigma": _std(y), "warmup": True,
                    "forecast": [level] * h,
                    "lower": [level - band] * h, "upper": [level + band] * h}
        return self._fit(y, n, m, h)

    def _fit(self, y, n, m, h):
        raise NotImplementedError   # filled in Task 3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_holt_winters.py -v`
Expected: PASS (protocol, empty, warm-up, zero-horizon). `_fit` is not reached by these cases.

- [ ] **Step 5: Commit**

```bash
git add fleet/forecast/holt_winters.py tests/test_holt_winters.py
git commit -m "feat(forecast): Holt-Winters skeleton — empty & warm-up paths"
```

---

## Task 3: Holt-Winters recurrence (level + trend + seasonality)

**Files:**
- Modify: `fleet/forecast/holt_winters.py` (`_fit`)
- Test: `tests/test_holt_winters.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_holt_winters.py`:

```python
def test_trend_series_forecasts_upward():
    # strictly increasing series, season_length small -> forecast keeps rising
    hist = [float(i) for i in range(24)]      # 0,1,2,...,23
    out = _f({"SEASON_LENGTH": "4"}).forecast(hist, horizon_h=4)
    assert out["trend"] > 0
    assert out["forecast"][-1] > out["forecast"][0]
    assert out["forecast"][0] > hist[-1] - 5    # continues near the last value, not flat


def test_seasonal_pattern_is_reproduced():
    # repeating season [2, 10, 4] over 6 cycles; m=3
    base = [2.0, 10.0, 4.0]
    hist = base * 6
    out = _f({"SEASON_LENGTH": "3"}).forecast(hist, horizon_h=3)
    fc = out["forecast"]
    # the next step continues the cycle: peak (10) should be the largest of the 3
    assert max(fc) == fc[1]
    assert fc[1] > fc[0] and fc[1] > fc[2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_holt_winters.py::test_seasonal_pattern_is_reproduced -v`
Expected: FAIL — `NotImplementedError` from `_fit`.

- [ ] **Step 3: Write minimal implementation**

Replace the `_fit` stub in `fleet/forecast/holt_winters.py` with:

```python
    def _fit(self, y, n, m, h):
        # additive initialization from the first two seasons
        level = _mean(y[:m])
        trend = (_mean(y[m:2 * m]) - _mean(y[:m])) / m
        season = [y[i] - level for i in range(m)]
        residuals: List[float] = []
        for t in range(n):
            s_idx = t % m
            seasonal = season[s_idx]
            if t >= m:                                  # collect one-step residuals
                residuals.append(y[t] - (level + trend + seasonal))
            last_level = level
            level = self.alpha * (y[t] - seasonal) + (1 - self.alpha) * (level + trend)
            trend = self.beta * (level - last_level) + (1 - self.beta) * trend
            season[s_idx] = self.gamma * (y[t] - level) + (1 - self.gamma) * seasonal
        sigma = _std(residuals)
        band = self.z * sigma
        forecast, lower, upper = [], [], []
        for k in range(1, h + 1):
            seasonal = season[(n + k - 1) % m]
            point = level + k * trend + seasonal
            forecast.append(point)
            lower.append(point - band)
            upper.append(point + band)
        return {"level": level, "trend": trend, "sigma": sigma,
                "forecast": forecast, "lower": lower, "upper": upper}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_holt_winters.py -v`
Expected: PASS (trend rises, seasonal pattern reproduced, plus the earlier paths)

- [ ] **Step 5: Commit**

```bash
git add fleet/forecast/holt_winters.py tests/test_holt_winters.py
git commit -m "feat(forecast): Holt-Winters level+trend+seasonal recurrence"
```

---

## Task 4: Prediction intervals behave correctly

**Files:**
- Test only: `tests/test_holt_winters.py` (the interval math already exists from Task 3; this task pins its behavior)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_holt_winters.py`:

```python
def test_constant_series_has_tight_interval():
    hist = [5.0] * 24
    out = _f({"SEASON_LENGTH": "4"}).forecast(hist, horizon_h=2)
    assert out["sigma"] < 1e-6
    for f, lo, hi in zip(out["forecast"], out["lower"], out["upper"]):
        assert abs(hi - lo) < 1e-6          # no residual variance => zero-width band
        assert lo <= f <= hi


def test_noisier_series_has_wider_interval():
    import random
    rng = random.Random(0)
    base = [10.0, 20.0, 30.0, 40.0]
    calm = (base * 8)
    noisy = [v + rng.uniform(-8, 8) for v in (base * 8)]
    w_calm = _band_width(_f({"SEASON_LENGTH": "4"}).forecast(calm, 4))
    w_noisy = _band_width(_f({"SEASON_LENGTH": "4"}).forecast(noisy, 4))
    assert w_noisy > w_calm


def _band_width(out):
    return out["upper"][0] - out["lower"][0]
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `pytest tests/test_holt_winters.py::test_constant_series_has_tight_interval tests/test_holt_winters.py::test_noisier_series_has_wider_interval -v`
Expected: PASS (the interval logic from Task 3 already satisfies these). If `test_noisier_series_has_wider_interval` is flaky on the chosen seed, widen the noise range in the test (e.g. `-12, 12`) — do NOT change the forecaster. This task exists to lock the interval semantics with explicit tests.

- [ ] **Step 3: (no impl change needed)**

If both tests already pass, skip to commit. If `test_constant_series_has_tight_interval` fails, verify `_std(residuals)` returns `0.0` for an empty/constant residual list (it does: `_std` returns `0.0` for `len < 2`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_holt_winters.py
git commit -m "test(forecast): pin Holt-Winters prediction-interval semantics"
```

---

## Task 5: Factory selection (`FORECASTER_ENGINE=holt`)

**Files:**
- Modify: `fleet/factory.py`
- Test: `tests/test_factory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_factory.py`:

```python
def test_factory_selects_holt_winters_when_requested():
    from fleet.forecast.holt_winters import HoltWintersForecaster
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={"FORECASTER_ENGINE": "holt"}))
    assert isinstance(c.forecaster, HoltWintersForecaster)


def test_factory_defaults_to_ewma_forecaster():
    from fleet.forecast.ewma import EwmaForecaster
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={}))
    assert isinstance(c.forecaster, EwmaForecaster)
```

(If `test_factory.py` already imports `build_components`/`load_settings` at module scope, reuse those imports rather than re-importing inside the functions.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_factory.py::test_factory_selects_holt_winters_when_requested -v`
Expected: FAIL — the factory always returns `EwmaForecaster`, so the Holt-Winters assertion fails.

- [ ] **Step 3: Write minimal implementation**

In `fleet/factory.py`:

(a) Add an import near the existing `from fleet.forecast.ewma import EwmaForecaster`:

```python
from fleet.forecast.holt_winters import HoltWintersForecaster
```

(b) Before the `return Components(...)`, add the selection:

```python
    # Forecaster: Holt-Winters (level+trend+seasonality+intervals) when requested,
    # else the default EWMA. (prophet remains a future, unimplemented slot.)
    if settings.forecaster_engine == "holt":
        forecaster: Forecaster = HoltWintersForecaster(settings)
    else:
        forecaster = EwmaForecaster(settings)
```

(c) Change the `Components(...)` argument from `forecaster=EwmaForecaster(settings),` to:

```python
        forecaster=forecaster,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_factory.py -v`
Expected: PASS (holt selected on request, EWMA by default)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS — EWMA default path unchanged; new Holt-Winters tests green.

- [ ] **Step 6: Commit**

```bash
git add fleet/factory.py tests/test_factory.py
git commit -m "feat(forecast): factory selects Holt-Winters on FORECASTER_ENGINE=holt"
```

---

## Self-Review

**Spec coverage (§4.1, §4.2):** Holt-Winters level+trend+additive-seasonality recurrence (Task 3); prediction intervals from residual sigma (Tasks 3+4); warm-up degradation for short history (Task 2, the spec's "warm-up before trusting the forecast"); EWMA stays default + Holt-Winters selectable (Tasks 1, 5). Proactive signal (§4.3) is deferred to M-D as the spec intends.

**Placeholder scan:** the `_fit` `NotImplementedError` in Task 2 is intentional and replaced in Task 3 (TDD red→green), not a leftover placeholder. Every other step has concrete code.

**Type consistency:** `HoltWintersForecaster.forecast(history, horizon_h) -> dict` matches the `Forecaster` protocol (`interfaces.py:33`). Helpers `_mean`/`_std`/`_smooth` and instance fields `alpha/beta/gamma/m/z` are defined in Task 2 and used unchanged in Task 3. Returned dict always contains `forecast`/`lower`/`upper`; `_fit` adds `level/trend/sigma`. Factory uses `Forecaster` (already imported, `factory.py:8`).

**Determinism:** pure function of `history` — no RNG, no clock, no I/O.

---

## Follow-on

- **M-C**: forecast-residual detector consumes `{forecast, lower, upper}` from this module as its dynamic anomaly band; CUSUM detector added alongside.
- **M-D**: scoring-policy DecisionEngine consumes the proactive forecast signal (§4.3).
