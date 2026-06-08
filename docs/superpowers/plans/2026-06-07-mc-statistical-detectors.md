# M-C: Statistical Detectors (forecast-residual + CUSUM) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two temporal, history-aware demand-anomaly detectors — a **forecast-residual** detector (flags demand outside the Holt-Winters prediction band) and a **CUSUM** detector (flags slow regime drift a single-tick threshold misses) — plus principled **severity-from-magnitude**, layered on top of the kept `RuleDetector` (ground-truth) via a `CompositeDetector`. Selected by `DETECTOR_ENGINE`; the `rule` default is untouched.

**Architecture:** New detectors live in `fleet/detection/` and implement the existing `Detector` protocol (`detect(state) -> List[Event]`). Unlike the stateless `RuleDetector`/`ZScoreDetector`, these are **stateful objects** that keep an internal per-customer observation history across `detect()` calls (a ring buffer) — no `WorldState` schema change, still RNG-free and deterministic. The forecast-residual detector consumes an injected `Forecaster` that returns prediction intervals, so it requires a Holt-Winters-style forecaster (M-B), not EWMA. A `CompositeDetector` runs several detectors and concatenates their events; the factory wires `rule` (default, unchanged), `zscore`, `residual`, `cusum`, and `layered` (Rule + residual + CUSUM). A shared `fleet/detection/severity.py` maps a standardized exceedance to `EventSeverity`.

**Tech Stack:** Python stdlib (`math`). Depends on M-B's `HoltWintersForecaster`. pytest.

**Spec:** `docs/superpowers/specs/2026-06-07-core-modules-deepening-design.md` §5.1 (forecast-residual), §5.2 (CUSUM), §5.3 (severity from magnitude), §5 (keep RuleDetector for ground-truth). Cascade correlation (§5.4) is explicit stretch — NOT in this plan.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `config/settings.py` | `cusum_k`, `cusum_threshold`, `detector_min_history` knobs | add 3 fields + env parsing |
| `fleet/detection/severity.py` | pure `severity_from_z(z) -> EventSeverity` | create |
| `fleet/detection/forecast_residual.py` | `ForecastResidualDetector` (stateful, injected forecaster) | create |
| `fleet/detection/cusum.py` | `CusumDetector` (stateful, Welford running stats) | create |
| `fleet/detection/composite.py` | `CompositeDetector` (run + concat) | create |
| `fleet/factory.py` | select residual/cusum/layered; build forecaster before detector | modify |
| `tests/test_statistical_detectors.py` | unit tests for all three + severity | create |
| `tests/test_config.py`, `tests/test_factory.py` | new settings + factory selection | modify |

**Preserve:** `RuleDetector`, `ZScoreDetector`, and their tests are untouched. `DETECTOR_ENGINE=rule` (default) returns exactly today's `RuleDetector`.

---

## Task 1: Detector settings

**Files:**
- Modify: `config/settings.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_statistical_detector_defaults():
    s = load_settings(env={})
    assert s.cusum_k == 0.5
    assert s.cusum_threshold == 4.0
    assert s.detector_min_history == 8


def test_statistical_detector_env_override():
    s = load_settings(env={"CUSUM_THRESHOLD": "3.0", "DETECTOR_MIN_HISTORY": "12"})
    assert s.cusum_threshold == 3.0
    assert s.detector_min_history == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_statistical_detector_defaults -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'cusum_k'`

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add to `Settings` (after the M-B forecaster fields):

```python
    cusum_k: float = 0.5                  # M-C: CUSUM slack (std units) before accumulating
    cusum_threshold: float = 4.0          # M-C: CUSUM alarm threshold (std units)
    detector_min_history: int = 8         # M-C: obs before a statistical detector activates
```

In `load_settings`, add:

```python
        cusum_k=float(e.get("CUSUM_K", "0.5")),
        cusum_threshold=float(e.get("CUSUM_THRESHOLD", "4.0")),
        detector_min_history=int(e.get("DETECTOR_MIN_HISTORY", "8")),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_config.py
git commit -m "feat(detect): statistical-detector settings (cusum k/threshold, min_history)"
```

---

## Task 2: Severity-from-magnitude helper

**Files:**
- Create: `fleet/detection/severity.py`
- Test: `tests/test_statistical_detectors.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_statistical_detectors.py`:

```python
from fleet.contracts.state import EventSeverity
from fleet.detection.severity import severity_from_z


def test_severity_bands():
    assert severity_from_z(0.5) == EventSeverity.LOW
    assert severity_from_z(2.0) == EventSeverity.MEDIUM
    assert severity_from_z(3.0) == EventSeverity.HIGH
    assert severity_from_z(4.5) == EventSeverity.CRITICAL


def test_severity_monotonic():
    order = [EventSeverity.LOW, EventSeverity.MEDIUM, EventSeverity.HIGH,
             EventSeverity.CRITICAL]
    zs = [0.0, 2.0, 3.0, 4.0]
    sevs = [severity_from_z(z) for z in zs]
    assert [order.index(s) for s in sevs] == sorted(order.index(s) for s in sevs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_statistical_detectors.py::test_severity_bands -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.detection.severity'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/detection/severity.py`:

```python
"""Map a standardized anomaly magnitude (z = sigmas beyond expectation) to an
EventSeverity band (M-C §5.3). Shared by the forecast-residual and CUSUM
detectors so severity is principled, not hard-coded."""

from fleet.contracts.state import EventSeverity


def severity_from_z(z: float) -> EventSeverity:
    if z >= 4.0:
        return EventSeverity.CRITICAL
    if z >= 3.0:
        return EventSeverity.HIGH
    if z >= 2.0:
        return EventSeverity.MEDIUM
    return EventSeverity.LOW
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_statistical_detectors.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/detection/severity.py tests/test_statistical_detectors.py
git commit -m "feat(detect): severity-from-magnitude helper (z -> EventSeverity)"
```

---

## Task 3: Forecast-residual detector

**Files:**
- Create: `fleet/detection/forecast_residual.py`
- Test: `tests/test_statistical_detectors.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_statistical_detectors.py`:

```python
from fleet.contracts.interfaces import Detector
from fleet.detection.forecast_residual import ForecastResidualDetector
from fleet.forecast.holt_winters import HoltWintersForecaster
from fleet.contracts.state import EventType
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def _set_orders(state, cid, total):
    state.customers[cid].orders = {"SKU001": int(total)}


def test_residual_detector_conforms_to_protocol():
    s = load_settings(env={"SEASON_LENGTH": "3"})
    d = ForecastResidualDetector(s, HoltWintersForecaster(s))
    assert isinstance(d, Detector)


def test_residual_flags_demand_above_band():
    s = load_settings(env={"SEASON_LENGTH": "3", "DETECTOR_MIN_HISTORY": "6"})
    d = ForecastResidualDetector(s, HoltWintersForecaster(s))
    state = build_sample_state()
    # feed a stable history for C001, then a big spike
    for _ in range(12):
        _set_orders(state, "C001", 10)
        d.detect(state)
    _set_orders(state, "C001", 80)                  # large surge
    events = d.detect(state)
    surges = [e for e in events if e.event_type == EventType.DEMAND_SURGE
              and e.target == "C001"]
    assert len(surges) == 1
    assert surges[0].id == "DET_RESID_C001"


def test_residual_quiet_when_demand_in_band():
    s = load_settings(env={"SEASON_LENGTH": "3", "DETECTOR_MIN_HISTORY": "6"})
    d = ForecastResidualDetector(s, HoltWintersForecaster(s))
    state = build_sample_state()
    events = []
    for _ in range(14):
        _set_orders(state, "C001", 10)              # perfectly stable
        events = d.detect(state)
    c001 = [e for e in events if e.target == "C001"]
    assert c001 == []                               # no false positive on stable demand
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_statistical_detectors.py::test_residual_flags_demand_above_band -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.detection.forecast_residual'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/detection/forecast_residual.py`:

```python
"""Forecast-residual demand detector (M-C §5.1): per customer, forecast the next
order volume from the customer's own history (via an injected interval-producing
Forecaster, e.g. Holt-Winters) and flag DEMAND_SURGE when the actual exceeds the
upper prediction band. Dynamic, context-aware threshold — the band is wide at
rush hour, narrow overnight. Stateful (keeps per-customer history); deterministic
(no RNG). Pairs with the kept RuleDetector via CompositeDetector."""

from typing import Dict, List

from fleet.contracts.state import WorldState, Event, EventType
from fleet.detection.severity import severity_from_z

_MAX_HISTORY = 240          # ring-buffer cap per customer


class ForecastResidualDetector:
    def __init__(self, settings=None, forecaster=None):
        if forecaster is None:                       # lazy default avoids import cycle at module top
            from fleet.forecast.holt_winters import HoltWintersForecaster
            forecaster = HoltWintersForecaster(settings)
        self.forecaster = forecaster
        self.min_history = int(getattr(settings, "detector_min_history", 8) or 8)
        self.history: Dict[str, List[float]] = {}

    def detect(self, state: WorldState) -> List[Event]:
        events: List[Event] = []
        for cid in sorted(state.customers):
            obs = float(sum(state.customers[cid].orders.values()))
            hist = self.history.setdefault(cid, [])
            if len(hist) >= self.min_history:
                out = self.forecaster.forecast(hist, 1)
                upper = out["upper"][0]
                if not out.get("warmup") and obs > upper:
                    point = out["forecast"][0]
                    sigma = out.get("sigma", 0.0)
                    z = (obs - point) / sigma if sigma > 1e-9 else 4.0
                    events.append(Event(
                        id=f"DET_RESID_{cid}", event_type=EventType.DEMAND_SURGE,
                        target=cid, severity=severity_from_z(z),
                        started_at=state.clock,
                        description=f"demand {obs:.0f} above forecast band {upper:.1f} at {cid}",
                        metrics={"actual": obs, "upper": float(upper), "z": float(z)}))
            hist.append(obs)
            if len(hist) > _MAX_HISTORY:
                del hist[0]
        return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_statistical_detectors.py -v`
Expected: PASS (protocol, surge flagged, stable demand quiet)

- [ ] **Step 5: Commit**

```bash
git add fleet/detection/forecast_residual.py tests/test_statistical_detectors.py
git commit -m "feat(detect): forecast-residual demand detector (dynamic band)"
```

---

## Task 4: CUSUM detector

**Files:**
- Create: `fleet/detection/cusum.py`
- Test: `tests/test_statistical_detectors.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_statistical_detectors.py`:

```python
from fleet.detection.cusum import CusumDetector


def test_cusum_conforms_to_protocol():
    assert isinstance(CusumDetector(load_settings()), Detector)


def test_cusum_flags_sustained_upward_drift():
    s = load_settings(env={"DETECTOR_MIN_HISTORY": "6", "CUSUM_THRESHOLD": "4.0"})
    d = CusumDetector(s)
    state = build_sample_state()
    # establish a stable baseline
    for _ in range(10):
        _set_orders(state, "C001", 10)
        d.detect(state)
    # then a sustained higher level (regime shift) -> CUSUM accumulates -> alarm
    fired = False
    for _ in range(10):
        _set_orders(state, "C001", 16)
        events = d.detect(state)
        if any(e.id == "DET_CUSUM_C001" for e in events):
            fired = True
            break
    assert fired


def test_cusum_quiet_on_stable_demand():
    s = load_settings(env={"DETECTOR_MIN_HISTORY": "6"})
    d = CusumDetector(s)
    state = build_sample_state()
    fired = False
    for _ in range(30):
        _set_orders(state, "C001", 10)
        if any(e.id == "DET_CUSUM_C001" for e in d.detect(state)):
            fired = True
    assert not fired
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_statistical_detectors.py::test_cusum_flags_sustained_upward_drift -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.detection.cusum'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/detection/cusum.py`:

```python
"""CUSUM drift detector (M-C §5.2): catches slow upward regime shifts in demand
that a single-tick threshold misses, by accumulating standardized deviations
above a slack k and alarming when the sum crosses a threshold h. Per customer,
running mean/variance via Welford. Stateful, deterministic (no RNG). Emits a
DEMAND_SURGE event and resets the accumulator after firing."""

import math
from typing import Dict, List

from fleet.contracts.state import WorldState, Event, EventType
from fleet.detection.severity import severity_from_z


class _Running:
    """Welford online mean/variance."""
    __slots__ = ("n", "mean", "m2", "cusum")

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.cusum = 0.0

    def update(self, x: float) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (x - self.mean)

    @property
    def std(self) -> float:
        return math.sqrt(self.m2 / (self.n - 1)) if self.n > 1 else 0.0


class CusumDetector:
    def __init__(self, settings=None):
        self.k = float(getattr(settings, "cusum_k", 0.5) or 0.5)
        self.h = float(getattr(settings, "cusum_threshold", 4.0) or 4.0)
        self.min_history = int(getattr(settings, "detector_min_history", 8) or 8)
        self.stats: Dict[str, _Running] = {}

    def detect(self, state: WorldState) -> List[Event]:
        events: List[Event] = []
        for cid in sorted(state.customers):
            obs = float(sum(state.customers[cid].orders.values()))
            r = self.stats.setdefault(cid, _Running())
            if r.n >= self.min_history and r.std > 1e-9:
                z = (obs - r.mean) / r.std
                r.cusum = max(0.0, r.cusum + z - self.k)
                if r.cusum >= self.h:
                    events.append(Event(
                        id=f"DET_CUSUM_{cid}", event_type=EventType.DEMAND_SURGE,
                        target=cid, severity=severity_from_z(r.cusum),
                        started_at=state.clock,
                        description=f"sustained demand drift at {cid} (cusum {r.cusum:.1f})",
                        metrics={"cusum": float(r.cusum), "mean": float(r.mean)}))
                    r.cusum = 0.0                    # reset after alarm
            r.update(obs)
        return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_statistical_detectors.py -v`
Expected: PASS (drift fires, stable quiet)

- [ ] **Step 5: Commit**

```bash
git add fleet/detection/cusum.py tests/test_statistical_detectors.py
git commit -m "feat(detect): CUSUM drift detector (regime-shift alarm)"
```

---

## Task 5: CompositeDetector + factory wiring

**Files:**
- Create: `fleet/detection/composite.py`
- Modify: `fleet/factory.py`
- Test: `tests/test_statistical_detectors.py`, `tests/test_factory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_statistical_detectors.py`:

```python
from fleet.detection.composite import CompositeDetector
from fleet.detection.rules import RuleDetector


def test_composite_concatenates_member_events():
    s = load_settings(env={"DETECTOR_MIN_HISTORY": "6", "SEASON_LENGTH": "3"})
    comp = CompositeDetector([
        RuleDetector(s),
        CusumDetector(s),
    ])
    state = build_sample_state()
    # RuleDetector fires on the sample world's permanently FLOODED #2 edge each call
    events = comp.detect(state)
    assert any(e.id.startswith("DET_FLOOD_") for e in events)
    assert isinstance(events, list)
```

Add to `tests/test_factory.py`:

```python
def test_factory_selects_layered_detector():
    from fleet.detection.composite import CompositeDetector
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={"DETECTOR_ENGINE": "layered"}))
    assert isinstance(c.detector, CompositeDetector)


def test_factory_defaults_to_rule_detector():
    from fleet.detection.rules import RuleDetector
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={}))
    assert isinstance(c.detector, RuleDetector)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_statistical_detectors.py::test_composite_concatenates_member_events -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.detection.composite'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/detection/composite.py`:

```python
"""CompositeDetector (M-C §5): run several Detectors and concatenate their events,
so the deterministic RuleDetector (ground-truth) and the statistical detectors
(forecast-residual, CUSUM) layer cleanly behind the single Detector interface.
The loop's DET_* lifecycle + dedup handle repeats."""

from typing import List

from fleet.contracts.state import WorldState, Event


class CompositeDetector:
    def __init__(self, detectors: list):
        self.detectors = list(detectors)

    def detect(self, state: WorldState) -> List[Event]:
        events: List[Event] = []
        for d in self.detectors:
            events.extend(d.detect(state))
        return events
```

In `fleet/factory.py`:

(a) Add imports near the other detector imports:

```python
from fleet.detection.forecast_residual import ForecastResidualDetector
from fleet.detection.cusum import CusumDetector
from fleet.detection.composite import CompositeDetector
```

(b) Ensure the **forecaster is built before the detector** (the residual detector needs it). Move the forecaster-selection block (from M-B) above the detector block if it is not already. Then replace the detector-selection block with:

```python
    # Detector: statistical detectors (history-aware) when requested, the layered
    # composite (ground-truth RuleDetector + residual + CUSUM), else the default
    # rule-based threshold detector. zscore kept for back-compat.
    if settings.detector_engine == "zscore":
        detector: Detector = ZScoreDetector(settings)
    elif settings.detector_engine == "residual":
        detector = ForecastResidualDetector(settings, forecaster)
    elif settings.detector_engine == "cusum":
        detector = CusumDetector(settings)
    elif settings.detector_engine == "layered":
        detector = CompositeDetector([
            RuleDetector(settings),
            ForecastResidualDetector(settings, forecaster),
            CusumDetector(settings),
        ])
    else:
        detector = RuleDetector(settings)
```

Note: pass the **same** `forecaster` instance the factory already built (M-B) so `residual`/`layered` reuse it. If `forecaster_engine` is the default EWMA, the residual detector still works only with an interval-producing forecaster — so when `detector_engine` is `residual`/`layered`, construct a `HoltWintersForecaster(settings)` for the detector explicitly rather than reusing a possibly-EWMA `forecaster`:

```python
    from fleet.forecast.holt_winters import HoltWintersForecaster
    interval_forecaster = (forecaster if isinstance(forecaster, HoltWintersForecaster)
                           else HoltWintersForecaster(settings))
```

and use `interval_forecaster` in the `residual`/`layered` branches.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_statistical_detectors.py tests/test_factory.py -v`
Expected: PASS (composite concatenates; factory selects layered; default still RuleDetector)

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS — `DETECTOR_ENGINE=rule` default unchanged; new detector tests green.

- [ ] **Step 6: Headless smoke with the layered detector + weather**

Run (PowerShell): `$env:DETECTOR_ENGINE="layered"; $env:ENABLE_WEATHER="1"; python -m fleet.loop; Remove-Item Env:\DETECTOR_ENGINE; Remove-Item Env:\ENABLE_WEATHER`
Expected: runs clean; flood (weather) + demand-surge (residual/CUSUM) events appear over the run (no traceback).

- [ ] **Step 7: Commit**

```bash
git add fleet/detection/composite.py fleet/factory.py tests/test_statistical_detectors.py tests/test_factory.py
git commit -m "feat(detect): CompositeDetector + factory wiring (residual/cusum/layered)"
```

---

## Self-Review

**Spec coverage (§5):** RuleDetector kept for ground-truth (untouched; layered, not replaced); forecast-residual detector with dynamic band (Task 3, §5.1); CUSUM drift detector (Task 4, §5.2); severity-from-magnitude (Task 2, §5.3); layered selection via `DETECTOR_ENGINE` (Task 5). Cascade correlation (§5.4) is spec-marked stretch — explicitly out of scope.

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** all three detectors implement `detect(self, state: WorldState) -> List[Event]` (matches `interfaces.py` Detector). `severity_from_z(z) -> EventSeverity` defined Task 2, used in Tasks 3–4. `ForecastResidualDetector(settings, forecaster=None)` and `CusumDetector(settings)` signatures match the factory calls in Task 5. Event ids `DET_RESID_{cid}` / `DET_CUSUM_{cid}` / `DET_FLOOD_{edge}` are deterministic (loop dedup-safe). The forecaster contract used (`forecast(hist,1)` returning `forecast`/`upper`/`sigma`/`warmup`) matches M-B's `HoltWintersForecaster`.

**Determinism:** no RNG anywhere; detectors are pure functions of their accumulated observation history, which is itself a deterministic function of the (seeded) simulator.

**Coupling check:** residual detector depends on M-B's interval forecaster — the factory guards this by constructing a `HoltWintersForecaster` for the detector regardless of `FORECASTER_ENGINE`.

---

## Follow-on

- **M-D**: scoring-policy DecisionEngine — consumes these richer events and the Forecaster proactive signal (§4.3).
- **Stretch (§5.4)**: cascade correlation — group events sharing one causal chain into a root-cause + consequences.
