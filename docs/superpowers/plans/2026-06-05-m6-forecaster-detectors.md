# M6 — Real EwmaForecaster + RuleDetector + ZScoreDetector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the M1 stubs behind the `Forecaster` and `Detector` interfaces with real implementations — exponential-smoothing demand forecasting (`EwmaForecaster`), threshold-rule disruption detection over the road graph + fleet (`RuleDetector`), and a statistical demand-anomaly detector (`ZScoreDetector`) — all pure, deterministic, config-driven, and selectable from `config/settings.py`.

**Architecture:** Each impl stays behind its existing single-method Protocol (`Forecaster.forecast(history, horizon_h) -> dict`, `Detector.detect(state) -> List[Event]`), so the loop/factory wiring is unchanged except for selection. Forecasting is classic single-exponential smoothing (level recurrence, flat multi-step forecast). `RuleDetector` walks `state.road_graph.edges` and `state.vehicles` and emits `Event`s for blocked/flooded/congested edges and broken vehicles. `ZScoreDetector` computes a **cross-sectional** z-score of each customer's current order volume against the fleet's customers (no history buffer needed) and flags outliers as `DEMAND_SURGE`. Everything is tested by calling the methods directly with constructed inputs — no loop, no network, no new dependency.

**Tech Stack:** Python 3.10+ standard library (`math`), dataclasses, pytest. No new dependency. Same repo/venv/branch.

---

## Context

- Continues branch **`feat/base-project`** (plans 1–8: M0–M5 complete & green; 115 passing after M5).
- Implements the M6 milestone: "real `EwmaForecaster` + `ZScoreDetector` (demand forecasting + statistical anomaly detection behind the `Forecaster`/`Detector` interfaces, selected by `config/settings.py`)." This plan also upgrades the `RuleDetector` stub to real threshold rules (the default `Detector`).

**Verified facts from the current code:**
- Interfaces (`fleet/contracts/interfaces.py`): `Forecaster.forecast(self, history: list, horizon_h: int) -> dict`; `Detector.detect(self, state: WorldState) -> List[Event]`.
- Current stubs: `fleet/forecast/ewma.py` `EwmaForecaster.forecast(...)` returns `{}`; `fleet/detection/rules.py` `RuleDetector.detect(...)` returns `[]`.
- `Event(id, event_type, target, severity, started_at, description="", metrics={}, ended_at=None)`. `EventType`: `TRAFFIC, DEMAND_SURGE, INVENTORY_SHORTAGE, VEHICLE_BREAKDOWN, URGENT_ORDER, FLOODED_AREA`. `EventSeverity`: `LOW, MEDIUM, HIGH, CRITICAL`.
- `EdgeStatus`: `OPEN, CONGESTED, BLOCKED, FLOODED`. `RoadEdge` has `id`, `from_node`, `to_node`, `traffic_factor`, `status`, `flood_level`. `RoadGraph.edges: Dict[str, RoadEdge]`.
- `VehicleStatus`: `AT_DEPOT, IN_TRANSIT, ON_ROUTE, BROKEN, MAINTENANCE`. `state.vehicles: Dict[str, Vehicle]`.
- `CustomerProfile.orders: Dict[str, int]` (sku→qty); `state.customers: Dict[str, CustomerProfile]`. `state.clock` is a datetime.
- `config/settings.py` already has `forecaster_engine: str = "ewma"  # ewma | prophet`, `detector_engine: str = "rule"  # rule | zscore`, and the frozen-dataclass + `load_settings(env)` pattern used by every prior milestone (see `solver_time_limit_sec` for the int example).
- The factory currently builds `RuleDetector()` and `EwmaForecaster()` with no args.

**Modeling decisions (documented in code):**
- **EWMA** is single (level-only) exponential smoothing: `level_0 = history[0]`, `level_t = α·obs_t + (1-α)·level_{t-1}`; the `horizon_h`-step forecast is **flat** at the final level (standard for SES). Returns `{"level": float, "alpha": float, "forecast": [float]*horizon_h}`. Empty history → level `0.0` and a zero forecast; `horizon_h <= 0` → empty `forecast` list. `α` from `settings.ewma_alpha` (default `0.3`), clamped to `(0, 1]`.
- **RuleDetector** emits at most one event per edge/vehicle, with **deterministic ids** (`DET_<KIND>_<target>`) so the loop's within-tick dedup (detected + active by id) is stable. Rules: `BLOCKED`→`TRAFFIC`/`CRITICAL`; `FLOODED`→`FLOODED_AREA` (`HIGH` if `flood_level ≥ 0.5` else `MEDIUM`); else `traffic_factor ≥ settings.traffic_alert_factor`→`TRAFFIC` (`HIGH` if `≥ 2×` the threshold else `MEDIUM`); vehicle `BROKEN`→`VEHICLE_BREAKDOWN`/`CRITICAL`. Pure/read-only over `state` (does not mutate `state.events`). Cross-tick re-surfacing of persistent conditions is a loop concern, out of scope here.
- **ZScoreDetector** is cross-sectional: for each customer, `total = sum(orders.values())`; compute mean/population-std across all customers; flag customers with `z = (total-mean)/std ≥ settings.zscore_threshold` (default `2.0`) as `DEMAND_SURGE` (`HIGH` if `z ≥ 3` else `MEDIUM`), id `DET_SURGE_<customer_id>`, `metrics={"z":…, "units":…}`. Needs `≥ 2` customers and `std > 0` (otherwise returns `[]`). This is genuinely statistical yet history-free, so it's deterministic and unit-testable without a demand buffer.
- Prophet (the `forecaster_engine == "prophet"` option) is **not** implemented in M6; the factory keeps returning `EwmaForecaster` regardless, with a comment. Only the detector gains a real selection branch (`rule` | `zscore`).

**Changes:** `config/settings.py` (+3 fields) + `tests/test_config.py`; `fleet/forecast/ewma.py` (rewrite) + new `tests/test_forecaster.py`; `fleet/detection/rules.py` (rewrite `RuleDetector`); new `fleet/detection/zscore.py` (`ZScoreDetector`); new `tests/test_detectors.py`; `fleet/factory.py` (detector selection + pass settings) + `tests/test_factory.py`.

Environment reminder (Windows / PowerShell): activate venv `.\.venv\Scripts\Activate.ps1`; run tests `pytest -v`; commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Only `git add` the files named in each task — do NOT touch `Guide.md`, `problem.txt`, `docs/PROBLEM_STATEMENT.md`.

---

### Task 1: Add forecaster/detector settings

**Files:**
- Modify: `config/settings.py` (`Settings` + `load_settings`)
- Test: `tests/test_config.py` (extend `test_defaults`, add env test)

- [ ] **Step 1: Write the failing test**

In `tests/test_config.py`, add to the end of `test_defaults` (the test asserting default values — match its existing variable name; it binds the result of `load_settings()`):
```python
    assert s.ewma_alpha == 0.3
    assert s.zscore_threshold == 2.0
    assert s.traffic_alert_factor == 3.0
```
And append a new test:
```python
def test_m6_setting_env_overrides():
    s = load_settings(env={"EWMA_ALPHA": "0.5",
                           "ZSCORE_THRESHOLD": "2.5",
                           "TRAFFIC_ALERT_FACTOR": "4"})
    assert s.ewma_alpha == 0.5
    assert s.zscore_threshold == 2.5
    assert s.traffic_alert_factor == 4.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'ewma_alpha'`.

- [ ] **Step 3: Add the settings**

In `config/settings.py`, add to the `Settings` dataclass (after `solver_time_limit_sec`):
```python
    ewma_alpha: float = 0.3                # M6: EWMA smoothing factor (0,1]
    zscore_threshold: float = 2.0          # M6: demand-anomaly z-score cutoff
    traffic_alert_factor: float = 3.0      # M6: traffic_factor at/above this -> TRAFFIC event
```
In `load_settings`, add to the `Settings(...)` constructor call:
```python
        ewma_alpha=float(e.get("EWMA_ALPHA", "0.3")),
        zscore_threshold=float(e.get("ZSCORE_THRESHOLD", "2.0")),
        traffic_alert_factor=float(e.get("TRAFFIC_ALERT_FACTOR", "3")),
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add config/settings.py tests/test_config.py
git commit -m "feat(config): M6 forecaster/detector settings

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Real `EwmaForecaster`

**Files:**
- Modify: `fleet/forecast/ewma.py` (rewrite)
- Test: new `tests/test_forecaster.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_forecaster.py`:
```python
from fleet.forecast.ewma import EwmaForecaster
from config.settings import load_settings


def test_constant_series_forecasts_constant():
    f = EwmaForecaster(load_settings(env={"EWMA_ALPHA": "0.5"}))
    out = f.forecast([10.0, 10.0, 10.0], horizon_h=3)
    assert out["level"] == 10.0
    assert out["alpha"] == 0.5
    assert out["forecast"] == [10.0, 10.0, 10.0]


def test_smoothing_recurrence_matches_hand_calc():
    # level0=0; +0.5*(10-0)=5; +0.5*(20-5)=12.5
    f = EwmaForecaster(load_settings(env={"EWMA_ALPHA": "0.5"}))
    out = f.forecast([0.0, 10.0, 20.0], horizon_h=2)
    assert out["level"] == 12.5
    assert out["forecast"] == [12.5, 12.5]


def test_empty_history_is_zero_forecast():
    f = EwmaForecaster(load_settings())
    out = f.forecast([], horizon_h=3)
    assert out["level"] == 0.0
    assert out["forecast"] == [0.0, 0.0, 0.0]


def test_nonpositive_horizon_returns_empty_forecast():
    f = EwmaForecaster(load_settings())
    out = f.forecast([1.0, 2.0], horizon_h=0)
    assert out["forecast"] == []


def test_default_alpha_when_no_settings():
    f = EwmaForecaster()           # settings optional
    out = f.forecast([5.0], horizon_h=1)
    assert out["alpha"] == 0.3
    assert out["forecast"] == [5.0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_forecaster.py -v`
Expected: FAIL — current stub takes no constructor arg and returns `{}`.

- [ ] **Step 3: Implement**

Replace the contents of `fleet/forecast/ewma.py`:
```python
"""EWMA demand forecaster (M6): single exponential smoothing.

level_0 = history[0]; level_t = alpha*obs_t + (1-alpha)*level_{t-1}. The
horizon-step forecast is flat at the final level (standard for SES). Pure and
deterministic. Prophet plugs in later behind the same Forecaster interface."""

from typing import Dict, List


class EwmaForecaster:
    def __init__(self, settings=None):
        alpha = float(getattr(settings, "ewma_alpha", 0.3) or 0.3)
        # clamp to (0, 1]
        self.alpha = min(1.0, max(1e-6, alpha))

    def forecast(self, history: list, horizon_h: int) -> Dict:
        horizon = max(0, int(horizon_h))
        if not history:
            return {"level": 0.0, "alpha": self.alpha,
                    "forecast": [0.0] * horizon}
        level = float(history[0])
        for obs in history[1:]:
            level = self.alpha * float(obs) + (1.0 - self.alpha) * level
        forecast: List[float] = [level] * horizon
        return {"level": level, "alpha": self.alpha, "forecast": forecast}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_forecaster.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: still green (the factory builds `EwmaForecaster()` with no args, which the optional `settings=None` constructor supports — no regression). Factory will pass settings in Task 5.

- [ ] **Step 6: Commit**

```
git add fleet/forecast/ewma.py tests/test_forecaster.py
git commit -m "feat(forecast): real EWMA single-exponential-smoothing forecaster

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Real `RuleDetector` (threshold rules)

**Files:**
- Modify: `fleet/detection/rules.py` (rewrite)
- Test: new `tests/test_detectors.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_detectors.py`:
```python
from datetime import datetime

from fleet.detection.rules import RuleDetector
from fleet.contracts.state import (
    WorldState, Depot, Location, RoadGraph, RoadEdge, RoadNode,
    Vehicle, VehicleStatus, EdgeStatus, EventType, EventSeverity,
)
from config.settings import load_settings


def _bare_state():
    depot = Depot(location=Location(0.0, 0.0, "", ""), inventory={},
                  opening_time=datetime(2026, 6, 4, 6, 0),
                  closing_time=datetime(2026, 6, 4, 18, 0))
    return WorldState(clock=datetime(2026, 6, 4, 7, 0), depot=depot)


def _put_edge(state, edge):
    state.road_graph.nodes.setdefault(
        edge.from_node, RoadNode(id=edge.from_node, location=Location(0.0, 0.0, "", "")))
    state.road_graph.edges[edge.id] = edge
    state.road_graph.adjacency.setdefault(edge.from_node, []).append(edge.id)


def test_blocked_edge_is_critical_traffic():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0, status=EdgeStatus.BLOCKED))
    events = RuleDetector(load_settings()).detect(s)
    e = next(ev for ev in events if ev.target == "A->B")
    assert e.event_type == EventType.TRAFFIC
    assert e.severity == EventSeverity.CRITICAL


def test_flooded_edge_severity_scales_with_depth():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0,
                          status=EdgeStatus.FLOODED, flood_level=0.6))
    e = RuleDetector(load_settings()).detect(s)[0]
    assert e.event_type == EventType.FLOODED_AREA
    assert e.severity == EventSeverity.HIGH


def test_high_traffic_factor_emits_traffic():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0, traffic_factor=3.5))
    e = RuleDetector(load_settings(env={"TRAFFIC_ALERT_FACTOR": "3"})).detect(s)[0]
    assert e.event_type == EventType.TRAFFIC
    assert e.severity == EventSeverity.MEDIUM     # 3.5 < 2*3


def test_normal_edge_emits_nothing():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0, traffic_factor=1.0))
    assert RuleDetector(load_settings()).detect(s) == []


def test_broken_vehicle_is_breakdown_event():
    s = _bare_state()
    s.vehicles["V001"] = Vehicle(id="V001", capacity_kg=500,
                                 pos=Location(0.0, 0.0, "", ""), current_load_kg=0.0,
                                 status=VehicleStatus.BROKEN)
    e = RuleDetector(load_settings()).detect(s)[0]
    assert e.event_type == EventType.VEHICLE_BREAKDOWN
    assert e.target == "V001"
    assert e.severity == EventSeverity.CRITICAL


def test_deterministic_ids_no_duplicates():
    s = _bare_state()
    _put_edge(s, RoadEdge("A", "B", 1.0, 5.0, status=EdgeStatus.BLOCKED))
    ev1 = RuleDetector(load_settings()).detect(s)
    ev2 = RuleDetector(load_settings()).detect(s)
    assert [e.id for e in ev1] == [e.id for e in ev2]   # stable across calls
    assert len({e.id for e in ev1}) == len(ev1)         # unique within a call
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_detectors.py -v`
Expected: FAIL — current `RuleDetector.detect` returns `[]`.

- [ ] **Step 3: Implement**

Replace the contents of `fleet/detection/rules.py`:
```python
"""Rule-based anomaly detector (M6): threshold rules over the road graph and
fleet. Pure/read-only over WorldState; emits one Event per offending edge/vehicle
with a deterministic id so the loop's within-tick dedup is stable.

ZScoreDetector (statistical demand anomalies) lives in fleet/detection/zscore.py
behind the same Detector interface."""

from typing import List

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity, EdgeStatus, VehicleStatus,
)

_FLOOD_HIGH_DEPTH = 0.5


class RuleDetector:
    def __init__(self, settings=None):
        self.alert_factor = float(getattr(settings, "traffic_alert_factor", 3.0)
                                  or 3.0)

    def detect(self, state: WorldState) -> List[Event]:
        events: List[Event] = []
        for edge in state.road_graph.edges.values():
            ev = self._edge_event(edge, state)
            if ev is not None:
                events.append(ev)
        for vehicle in state.vehicles.values():
            if vehicle.status == VehicleStatus.BROKEN:
                events.append(Event(
                    id=f"DET_BREAK_{vehicle.id}",
                    event_type=EventType.VEHICLE_BREAKDOWN, target=vehicle.id,
                    severity=EventSeverity.CRITICAL, started_at=state.clock,
                    description=f"vehicle {vehicle.id} broken down"))
        return events

    def _edge_event(self, edge, state):
        if edge.status == EdgeStatus.BLOCKED:
            return Event(
                id=f"DET_BLOCK_{edge.id}", event_type=EventType.TRAFFIC,
                target=edge.id, severity=EventSeverity.CRITICAL,
                started_at=state.clock, description=f"edge {edge.id} blocked")
        if edge.status == EdgeStatus.FLOODED:
            sev = (EventSeverity.HIGH if edge.flood_level >= _FLOOD_HIGH_DEPTH
                   else EventSeverity.MEDIUM)
            return Event(
                id=f"DET_FLOOD_{edge.id}", event_type=EventType.FLOODED_AREA,
                target=edge.id, severity=sev, started_at=state.clock,
                description=f"edge {edge.id} flooded (depth {edge.flood_level})",
                metrics={"flood_level": float(edge.flood_level)})
        if edge.traffic_factor >= self.alert_factor:
            sev = (EventSeverity.HIGH
                   if edge.traffic_factor >= 2 * self.alert_factor
                   else EventSeverity.MEDIUM)
            return Event(
                id=f"DET_TRAFFIC_{edge.id}", event_type=EventType.TRAFFIC,
                target=edge.id, severity=sev, started_at=state.clock,
                description=f"edge {edge.id} congested (x{edge.traffic_factor})",
                metrics={"traffic_factor": float(edge.traffic_factor)})
        return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_detectors.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: still green. **Watch `tests/test_loop.py`:** `build_sample_state` includes a parallel FLOODED edge (`DEPOT->C001#2`, `flood_level=0.5`), so `RuleDetector` will now surface a `FLOODED_AREA` event each tick once the factory wires it in (Task 5) — but the loop's decision tests filter by their own injected `event_id`, so they remain valid. If `test_loop_advances_clock` or the severity tests fail after Task 5, re-read them: they must assert on their specific event/clock, not on total decision counts. (At this point, before Task 5, the factory still builds the old `RuleDetector()` with no args — which the new optional-`settings` constructor still supports — so the suite stays green here.)

- [ ] **Step 6: Commit**

```
git add fleet/detection/rules.py tests/test_detectors.py
git commit -m "feat(detection): real RuleDetector threshold rules (edges + fleet)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `ZScoreDetector` (statistical demand anomalies)

**Files:**
- Create: `fleet/detection/zscore.py`
- Test: `tests/test_detectors.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_detectors.py`:
```python
from fleet.detection.zscore import ZScoreDetector
from fleet.contracts.state import CustomerProfile, TimeWindow


def _add_customer(state, cid, units):
    state.customers[cid] = CustomerProfile(
        id=cid, type="market", location=Location(0.0, 0.0, "", ""),
        orders={"SKUX": units},
        time_window=TimeWindow(state.depot.opening_time,
                               state.depot.closing_time))


def test_outlier_customer_flagged_as_demand_surge():
    s = _bare_state()
    for cid in ("C001", "C002", "C003", "C004"):
        _add_customer(s, cid, 10)
    _add_customer(s, "C999", 200)        # extreme outlier
    events = ZScoreDetector(load_settings()).detect(s)
    targets = {e.target for e in events}
    assert "C999" in targets
    e = next(ev for ev in events if ev.target == "C999")
    assert e.event_type == EventType.DEMAND_SURGE
    assert e.severity == EventSeverity.HIGH       # z well above 3
    assert e.metrics["units"] == 200.0


def test_uniform_demand_emits_nothing():
    s = _bare_state()
    for cid in ("C001", "C002", "C003"):
        _add_customer(s, cid, 10)
    assert ZScoreDetector(load_settings()).detect(s) == []


def test_fewer_than_two_customers_emits_nothing():
    s = _bare_state()
    _add_customer(s, "C001", 50)
    assert ZScoreDetector(load_settings()).detect(s) == []


def test_threshold_is_configurable():
    s = _bare_state()
    for cid, u in (("C001", 10), ("C002", 10), ("C003", 10), ("C004", 22)):
        _add_customer(s, cid, u)
    # with a high cutoff, the mild outlier is ignored
    assert ZScoreDetector(load_settings(env={"ZSCORE_THRESHOLD": "5"})).detect(s) == []
    # with a low cutoff, it is flagged
    flagged = ZScoreDetector(load_settings(env={"ZSCORE_THRESHOLD": "1.2"})).detect(s)
    assert any(e.target == "C004" for e in flagged)
```
> Note: confirm `TimeWindow`'s constructor field order in `fleet/contracts/state.py` before running (it is used here as `TimeWindow(start, end)`). If its fields are named/ordered differently, adjust the `_add_customer` helper accordingly — this is the only spot that constructs one.

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_detectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.detection.zscore'`.

- [ ] **Step 3: Implement**

Create `fleet/detection/zscore.py`:
```python
"""Statistical demand-anomaly detector (M6).

Cross-sectional z-score: compares each customer's current total order volume to
the mean/std across all customers (population std). Customers whose z-score meets
settings.zscore_threshold are flagged DEMAND_SURGE. History-free, pure, and
deterministic. Same Detector interface as RuleDetector."""

import math
from typing import List

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity,
)

_HIGH_Z = 3.0


class ZScoreDetector:
    def __init__(self, settings=None):
        self.threshold = float(getattr(settings, "zscore_threshold", 2.0) or 2.0)

    def detect(self, state: WorldState) -> List[Event]:
        totals = {cid: float(sum(c.orders.values()))
                  for cid, c in state.customers.items()}
        n = len(totals)
        if n < 2:
            return []
        mean = sum(totals.values()) / n
        var = sum((v - mean) ** 2 for v in totals.values()) / n
        std = math.sqrt(var)
        if std == 0.0:
            return []
        events: List[Event] = []
        for cid in sorted(totals):                # deterministic order
            z = (totals[cid] - mean) / std
            if z >= self.threshold:
                sev = EventSeverity.HIGH if z >= _HIGH_Z else EventSeverity.MEDIUM
                events.append(Event(
                    id=f"DET_SURGE_{cid}", event_type=EventType.DEMAND_SURGE,
                    target=cid, severity=sev, started_at=state.clock,
                    description=f"demand surge at {cid} (z={z:.2f})",
                    metrics={"z": float(z), "units": totals[cid]}))
        return events
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_detectors.py -v`
Expected: PASS (RuleDetector + ZScoreDetector tests).

- [ ] **Step 5: Commit**

```
git add fleet/detection/zscore.py tests/test_detectors.py
git commit -m "feat(detection): ZScoreDetector cross-sectional demand-surge detection

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Factory selection + settings wiring

**Files:**
- Modify: `fleet/factory.py`
- Test: `tests/test_factory.py` (append)

- [ ] **Step 1: Write the failing test**

In `tests/test_factory.py`, add to the existing import block:
```python
from fleet.detection.rules import RuleDetector
from fleet.detection.zscore import ZScoreDetector
```
and append:
```python
def test_default_detector_is_rule():
    comps = build_components(load_settings(env={}))
    assert isinstance(comps.detector, RuleDetector)


def test_zscore_detector_selected_by_setting():
    comps = build_components(load_settings(env={"DETECTOR_ENGINE": "zscore"}))
    assert isinstance(comps.detector, ZScoreDetector)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_factory.py -v`
Expected: FAIL — `test_zscore_detector_selected_by_setting` fails (factory always builds `RuleDetector()`).

- [ ] **Step 3: Wire the factory**

In `fleet/factory.py`, add the import:
```python
from fleet.detection.zscore import ZScoreDetector
```
Add a detector-selection block (alongside the routing/decision blocks):
```python
    # Detector: statistical z-score anomaly detector when requested, else the
    # rule-based threshold detector (default).
    if settings.detector_engine == "zscore":
        detector: Detector = ZScoreDetector(settings)
    else:
        detector = RuleDetector(settings)
```
Update the `Components(...)` construction to use the selected detector and pass settings to the forecaster:
```python
    return Components(
        simulator=WorldSimulator(settings),
        detector=detector,
        optimizer=optimizer,
        forecaster=EwmaForecaster(settings),   # prophet not yet implemented (M6)
        decision_engine=decision_engine,
        dispatcher=DispatcherImpl(),
    )
```
> `Detector` and the `RuleDetector`/`EwmaForecaster` symbols are already imported at the top of `fleet/factory.py` from prior milestones — only `ZScoreDetector` is new.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_factory.py -v`
Expected: PASS.

- [ ] **Step 5: Full suite + smoke run**

Run: `pytest -v` (expect all green — prior count plus the new config/forecaster/detector/factory tests).
Run: `python -m fleet.loop` (now the real `RuleDetector` runs each tick; the sample world's parallel flooded `DEPOT->C001#2` edge surfaces a `FLOODED_AREA` event → `REROUTE` decisions, in addition to the demo-injected `TRAFFIC`. Should run clean.)
> If any `tests/test_loop.py` test regressed, it is because the real detector now emits events the old stub didn't. The fix is in the **test** (assert on the specific injected `event_id`/clock, as those tests already do), never in the detector — confirm before changing anything.

- [ ] **Step 6: Commit**

```
git add fleet/factory.py tests/test_factory.py
git commit -m "feat(factory): select detector (rule|zscore) + pass settings to forecaster

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification checklist (end of plan)

- [ ] `pytest -v` fully green.
- [ ] `EwmaForecaster.forecast` implements the SES recurrence, returns `{level, alpha, forecast}`, handles empty history and non-positive horizon, and uses `settings.ewma_alpha` (default 0.3).
- [ ] `RuleDetector.detect` emits `TRAFFIC`(BLOCKED/CRITICAL & congested), `FLOODED_AREA`(depth-scaled), and `VEHICLE_BREAKDOWN`(CRITICAL) with deterministic ids, and nothing for a normal edge.
- [ ] `ZScoreDetector.detect` flags cross-sectional outlier customers as `DEMAND_SURGE`, returns `[]` for uniform demand / `<2` customers / zero std, and respects `settings.zscore_threshold`.
- [ ] Factory returns `ZScoreDetector` when `DETECTOR_ENGINE=zscore`, else `RuleDetector`; forecaster receives settings.
- [ ] No new dependency added; `python -m fleet.loop` runs clean.
- [ ] Only the files named in each task were committed (no `Guide.md`/`problem.txt`/`docs/PROBLEM_STATEMENT.md`).

**Completes M6.** Next milestone: **M7 — Streamlit UI** (a dashboard over the existing `WorldState` + `run_loop`: map/timeline, event feed, pending-decision approval controls — the final milestone in the base-project series).
