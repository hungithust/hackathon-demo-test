# M-A2: Simulator Traffic & Weather Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete spec §3.1 by adding the traffic + weather half of the latent process: a deterministic rush-hour traffic multiplier on open edges (kept below the alert threshold so it is *normal* traffic, not a false alarm) and an AR(1) weather/rain process that probabilistically floods and un-floods the flood-prone parallel edges — giving the Detector real transport structure to react to. 100% synthetic, seeded-deterministic, CPU, $0.

**Architecture:** All changes live in `fleet/simulator/engine.py` and `config/settings.py`. The whole feature is gated behind a new `enable_weather` setting that **defaults to False**, so the existing 157-passing suite is untouched; the loop/UI/Detector tests opt in via `ENABLE_WEATHER=1`. Weather/traffic draw from a **separate** `self._weather_rng` (seeded `seed + 1`) so the demand random stream — and thus M-A's determinism — is byte-identical whether weather is on or off. Edge mutation respects the injection overlay (§3.2): traffic only modulates `OPEN` edges (leaving presenter-injected BLOCKED/FLOODED/CONGESTED edges alone), and weather only toggles the edges it owns (a lazily-snapshotted flood-prone set).

**Tech Stack:** Python stdlib only (`random`, `datetime`). No new dependency. pytest.

**Spec:** `docs/superpowers/specs/2026-06-07-core-modules-deepening-design.md` §3.1 (traffic = rush-hour × weather → probabilistic flooding) and §3.2 (injection-as-override). Builds on M-A (demand latent-process, already merged).

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `config/settings.py` | weather/traffic knobs + `enable_weather` gate | add 5 fields + env parsing |
| `fleet/simulator/engine.py` | `_traffic_factor_for_hour` pure helper; `WorldSimulator` weather rng + rain state + `_step_rain`/`_update_traffic`/`_update_weather`; call from `tick` | modify |
| `tests/test_weather.py` | new tests for traffic helper, rain process, edge toggling, injection-respect, gate-off no-op | create |
| `tests/test_config.py` | assert new settings defaults + env override | modify |

**Preserve (do NOT break):** with `enable_weather=False` (default), `tick` behaves exactly as after M-A — assert this explicitly (Task 6). The demand stream must stay identical on/off (separate rng).

---

## Task 1: Weather/traffic settings

**Files:**
- Modify: `config/settings.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_weather_defaults():
    s = load_settings(env={})
    assert s.enable_weather is False
    assert s.traffic_peak_factor == 1.8
    assert s.weather_rho == 0.8
    assert s.weather_flood_threshold == 0.7
    assert s.weather_flood_level == 0.5


def test_weather_env_override():
    s = load_settings(env={"ENABLE_WEATHER": "1", "TRAFFIC_PEAK_FACTOR": "2.2"})
    assert s.enable_weather is True
    assert s.traffic_peak_factor == 2.2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_weather_defaults -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'enable_weather'`

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add to the `Settings` dataclass (after the M-A regime fields):

```python
    enable_weather: bool = False          # M-A2: gate traffic+weather edge mutation
    traffic_peak_factor: float = 1.8      # M-A2: rush-hour traffic_factor at peak (< traffic_alert_factor)
    weather_rho: float = 0.8              # M-A2: AR(1) autocorrelation of the rain process
    weather_flood_threshold: float = 0.7  # M-A2: rain level at/above which flood-prone edges flood
    weather_flood_level: float = 0.5      # M-A2: flood depth applied while flooded (m)
```

In `load_settings`, add to the `Settings(...)` call:

```python
        enable_weather=e.get("ENABLE_WEATHER", "0") in ("1", "true", "True"),
        traffic_peak_factor=float(e.get("TRAFFIC_PEAK_FACTOR", "1.8")),
        weather_rho=float(e.get("WEATHER_RHO", "0.8")),
        weather_flood_threshold=float(e.get("WEATHER_FLOOD_THRESHOLD", "0.7")),
        weather_flood_level=float(e.get("WEATHER_FLOOD_LEVEL", "0.5")),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config/settings.py tests/test_config.py
git commit -m "feat(sim): weather/traffic settings (enable_weather gate, peak/rho/flood knobs)"
```

---

## Task 2: Rush-hour traffic helper

**Files:**
- Modify: `fleet/simulator/engine.py`
- Test: `tests/test_weather.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_weather.py`:

```python
from datetime import timedelta

from fleet.contracts.state import EdgeStatus
from fleet.simulator.engine import WorldSimulator, _traffic_factor_for_hour
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def test_traffic_peaks_at_rush_hours_and_stays_below_alert():
    peak = 1.8
    alert = 3.0
    assert _traffic_factor_for_hour(8, peak) == peak        # morning rush
    assert _traffic_factor_for_hour(18, peak) == peak       # evening rush
    assert _traffic_factor_for_hour(13, peak) < peak        # midday lighter
    assert _traffic_factor_for_hour(3, peak) == 1.0         # night = free flow
    assert _traffic_factor_for_hour(8, peak) < alert        # never a false TRAFFIC alert
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_weather.py::test_traffic_peaks_at_rush_hours_and_stays_below_alert -v`
Expected: FAIL — `ImportError: cannot import name '_traffic_factor_for_hour'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/simulator/engine.py`, add a module-level helper below `_trend_factor` (from M-A):

```python
def _traffic_factor_for_hour(hour: int, peak_factor: float) -> float:
    """Rush-hour congestion multiplier. Peaks (peak_factor) in the morning/evening
    commute, mild at midday, free-flow (1.0) overnight. Caller keeps peak_factor
    below settings.traffic_alert_factor so normal rush hour is not a TRAFFIC alert."""
    if 6 <= hour < 10 or 16 <= hour < 20:
        return peak_factor
    if 10 <= hour < 16:
        return 1.0 + 0.4 * (peak_factor - 1.0)   # ~midday, between free-flow and peak
    return 1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_weather.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_weather.py
git commit -m "feat(sim): rush-hour traffic factor helper (bounded below alert)"
```

---

## Task 3: AR(1) rain process

**Files:**
- Modify: `fleet/simulator/engine.py` (`__init__`: weather rng + rain; `_step_rain`)
- Test: `tests/test_weather.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_weather.py`:

```python
def test_rain_is_bounded_autocorrelated_and_deterministic():
    s1 = WorldSimulator(load_settings(env={"SEED": "5", "WEATHER_RHO": "0.9"}))
    s2 = WorldSimulator(load_settings(env={"SEED": "5", "WEATHER_RHO": "0.9"}))
    xs = [s1._step_rain() for _ in range(300)]
    ys = [s2._step_rain() for _ in range(300)]
    assert xs == ys                              # same seed => identical
    assert all(0.0 <= r <= 1.0 for r in xs)      # rain level normalized to [0,1]
    a, b = xs[:-1], xs[1:]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    assert cov / (va * vb) > 0.4                  # rho=0.9 => persistent rain spells


def test_weather_rng_is_independent_of_demand_rng():
    # Stepping rain must not consume the demand rng (so M-A determinism is unaffected).
    sim = WorldSimulator(load_settings(env={"SEED": "42"}))
    before = sim.rng.random()
    sim2 = WorldSimulator(load_settings(env={"SEED": "42"}))
    sim2._step_rain(); sim2._step_rain(); sim2._step_rain()
    after = sim2.rng.random()
    assert before == after        # demand rng stream unchanged by rain steps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_weather.py::test_rain_is_bounded_autocorrelated_and_deterministic -v`
Expected: FAIL — `AttributeError: 'WorldSimulator' object has no attribute '_step_rain'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/simulator/engine.py`, `WorldSimulator.__init__`, add (next to the M-A `self._ar_state`):

```python
        self._weather_rng = random.Random(settings.seed + 1)  # M-A2: independent of demand rng
        self._rain = 0.0                                      # M-A2: rain level in [0,1]
        self._flood_prone = None                              # M-A2: lazily-snapshotted edge ids
        self._weather_flooded: set = set()                    # M-A2: edges flooded BY weather
```

Add a method (place below the M-A `_regime_multiplier`):

```python
    def _step_rain(self) -> float:
        """AR(1) rain process in [0,1]: rho keeps rain spells persistent.
        Uses the independent weather rng so the demand stream is untouched."""
        rho = self.settings.weather_rho
        shock = self._weather_rng.random()
        self._rain = max(0.0, min(1.0, rho * self._rain + (1.0 - rho) * shock))
        return self._rain
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_weather.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_weather.py
git commit -m "feat(sim): AR(1) rain process on an independent weather rng"
```

---

## Task 4: Apply rush-hour traffic to open edges

**Files:**
- Modify: `fleet/simulator/engine.py` (`_update_traffic`)
- Test: `tests/test_weather.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_weather.py`:

```python
def test_update_traffic_only_touches_open_edges():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"TRAFFIC_PEAK_FACTOR": "1.8"}))
    # disrupt one edge (presenter injection): congested with a big factor
    s.road_graph.get_edge("DEPOT->C001").status = EdgeStatus.CONGESTED
    s.road_graph.get_edge("DEPOT->C001").traffic_factor = 4.0
    s.clock = s.clock.replace(hour=8)            # morning rush
    sim._update_traffic(s)
    # an OPEN edge gets the rush-hour factor
    assert s.road_graph.get_edge("DEPOT->C002").traffic_factor == 1.8
    # the injected CONGESTED edge is left alone (override respected)
    assert s.road_graph.get_edge("DEPOT->C001").traffic_factor == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_weather.py::test_update_traffic_only_touches_open_edges -v`
Expected: FAIL — `AttributeError: 'WorldSimulator' object has no attribute '_update_traffic'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/simulator/engine.py`, add below `_step_rain`:

```python
    def _update_traffic(self, state: WorldState) -> None:
        """Set rush-hour congestion on OPEN edges only; injected/disrupted edges
        (BLOCKED/FLOODED/CONGESTED) keep their values (§3.2 injection override)."""
        factor = _traffic_factor_for_hour(
            state.clock.hour, self.settings.traffic_peak_factor)
        for edge in state.road_graph.edges.values():
            if edge.status == EdgeStatus.OPEN:
                edge.traffic_factor = factor
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_weather.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_weather.py
git commit -m "feat(sim): rush-hour traffic on open edges (respects injection override)"
```

---

## Task 5: Weather-driven flooding of flood-prone edges

**Files:**
- Modify: `fleet/simulator/engine.py` (`_update_weather`)
- Test: `tests/test_weather.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_weather.py`:

```python
def test_weather_floods_and_recovers_flood_prone_edges():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"WEATHER_FLOOD_THRESHOLD": "0.7"}))
    fp = "DEPOT->C001#2"                          # flood-prone parallel edge from the sample world
    # force heavy rain -> flood
    sim._rain = 0.9
    sim._update_weather(s)
    assert s.road_graph.get_edge(fp).status == EdgeStatus.FLOODED
    assert s.road_graph.get_edge(fp).flood_level == 0.5
    # force dry -> the weather-owned edge recovers to OPEN
    sim._rain = 0.1
    sim._update_weather(s)
    assert s.road_graph.get_edge(fp).status == EdgeStatus.OPEN
    assert s.road_graph.get_edge(fp).flood_level == 0.0


def test_weather_does_not_touch_injected_flood_on_other_edges():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    # presenter injects a flood on a NON-flood-prone edge
    inj = s.road_graph.get_edge("DEPOT->C002")
    inj.status = EdgeStatus.FLOODED
    inj.flood_level = 0.8
    sim._rain = 0.1                               # dry: weather would un-flood its own edges
    sim._update_weather(s)
    assert inj.status == EdgeStatus.FLOODED       # injected edge untouched
    assert inj.flood_level == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_weather.py::test_weather_floods_and_recovers_flood_prone_edges -v`
Expected: FAIL — `AttributeError: 'WorldSimulator' object has no attribute '_update_weather'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/simulator/engine.py`, add below `_update_traffic`:

```python
    def _update_weather(self, state: WorldState) -> None:
        """Flood-prone edges (those starting flooded / with a baseline flood_level)
        flood when rain >= threshold and recover when it drops. Only edges weather
        itself owns are toggled, so presenter-injected floods elsewhere are safe."""
        if self._flood_prone is None:
            self._flood_prone = {
                eid for eid, e in state.road_graph.edges.items()
                if e.flood_level > 0.0 or e.status == EdgeStatus.FLOODED
            }
        flooding = self._rain >= self.settings.weather_flood_threshold
        for eid in self._flood_prone:
            edge = state.road_graph.get_edge(eid)
            if edge is None:
                continue
            if flooding:
                edge.status = EdgeStatus.FLOODED
                edge.flood_level = self.settings.weather_flood_level
                self._weather_flooded.add(eid)
            elif eid in self._weather_flooded:
                edge.status = EdgeStatus.OPEN
                edge.flood_level = 0.0
                self._weather_flooded.discard(eid)
```

Note: the flood-prone snapshot is taken on first call, so the sample world's permanently-flooded `#2` edges become weather-controlled (they recover when dry, flood when wet) — a realistic upgrade over the static flood.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_weather.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fleet/simulator/engine.py tests/test_weather.py
git commit -m "feat(sim): weather-driven flood/recover of flood-prone edges (injection-safe)"
```

---

## Task 6: Wire weather into `tick` behind the gate

**Files:**
- Modify: `fleet/simulator/engine.py` (`tick`)
- Test: `tests/test_weather.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_weather.py`:

```python
def test_gate_off_means_no_edge_mutation():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"ENABLE_WEATHER": "0"}))
    before = {eid: (e.status, e.traffic_factor, e.flood_level)
              for eid, e in s.road_graph.edges.items()}
    for _ in range(20):
        sim.tick(s)
    after = {eid: (e.status, e.traffic_factor, e.flood_level)
             for eid, e in s.road_graph.edges.items()}
    assert before == after        # weather off => edges never mutated by the sim


def test_gate_on_eventually_mutates_traffic():
    s = build_sample_state()
    sim = WorldSimulator(load_settings(env={"ENABLE_WEATHER": "1", "SEED": "3"}))
    open_edge = "DEPOT->C002"
    seen = set()
    for _ in range(60):
        sim.tick(s)
        seen.add(round(s.road_graph.get_edge(open_edge).traffic_factor, 3))
    assert len(seen) > 1          # traffic_factor varies across the day (rush vs off-peak)


def test_demand_stream_identical_with_weather_on_or_off():
    s_off = build_sample_state()
    s_on = build_sample_state()
    sim_off = WorldSimulator(load_settings(env={"SEED": "42", "ENABLE_WEATHER": "0"}))
    sim_on = WorldSimulator(load_settings(env={"SEED": "42", "ENABLE_WEATHER": "1"}))
    for _ in range(15):
        sim_off.tick(s_off)
        sim_on.tick(s_on)
    o_off = {cid: dict(c.orders) for cid, c in s_off.customers.items()}
    o_on = {cid: dict(c.orders) for cid, c in s_on.customers.items()}
    assert o_off == o_on          # separate weather rng => demand untouched by weather
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_weather.py::test_gate_on_eventually_mutates_traffic -v`
Expected: FAIL — `tick` does not yet call the weather methods, so `traffic_factor` never changes (only one value seen).

- [ ] **Step 3: Write minimal implementation**

In `fleet/simulator/engine.py`, in `tick`, add the weather step right after the start-clock capture (from M-A) and before `_generate_demand`:

```python
        if self.settings.enable_weather:
            self._step_rain()
            self._update_traffic(state)
            self._update_weather(state)
```

So `tick` reads (M-A lines plus this block):

```python
        if self._start_clock is None:
            self._start_clock = state.clock
        if self.settings.enable_weather:
            self._step_rain()
            self._update_traffic(state)
            self._update_weather(state)
        self._generate_demand(state)
```

- [ ] **Step 4: Run the weather suite**

Run: `pytest tests/test_weather.py -v`
Expected: PASS (gate off no-op, gate on mutates traffic, demand stream identical on/off)

- [ ] **Step 5: Run the FULL suite (gate-off must be a perfect no-op)**

Run: `pytest -q`
Expected: PASS — the same count as after M-A (default `enable_weather=False` changes nothing). If anything regresses, the gate or the separate-rng isolation is wrong; fix the **code**, not the tests.

- [ ] **Step 6: Headless smoke with weather ON**

Run (PowerShell): `$env:ENABLE_WEATHER="1"; python -m fleet.loop; Remove-Item Env:\ENABLE_WEATHER`
Expected: runs clean; with weather on you should see flood/traffic-driven events and reroutes over the run (no traceback).

- [ ] **Step 7: Commit**

```bash
git add fleet/simulator/engine.py tests/test_weather.py
git commit -m "feat(sim): wire weather/traffic into tick behind enable_weather gate"
```

---

## Self-Review

**Spec coverage (§3.1 traffic half + §3.2):** rush-hour traffic multiplier (Task 2, bounded below alert), AR(1) weather/rain (Task 3), traffic applied to open edges only (Task 4), probabilistic flood/recover of flood-prone edges (Task 5), gated wiring (Task 6). Injection-as-override (§3.2): Tasks 4 and 5 each assert presenter-injected edges are left untouched. §3.1 is now fully covered across M-A (demand) + M-A2 (traffic/weather).

**Placeholder scan:** none — every step has concrete code and commands.

**Type consistency:** `_traffic_factor_for_hour(hour, peak_factor)`, `_step_rain()`, `_update_traffic(state)`, `_update_weather(state)`; instance state `_weather_rng`, `_rain`, `_flood_prone`, `_weather_flooded` — names identical across Tasks 3–6. `EdgeStatus.OPEN/FLOODED/CONGESTED/BLOCKED` and `RoadEdge.status/traffic_factor/flood_level` confirmed against `state.py:176-184`. `road_graph.get_edge(eid)` and `road_graph.edges` confirmed against the architecture doc §7.

**Determinism & isolation:** weather uses `self._weather_rng` (seed+1), never the demand `self.rng`; Task 3 asserts the demand rng is untouched, Task 6 asserts the demand order stream is identical with weather on/off. Default gate off ⇒ zero behavior change ⇒ same pytest count as after M-A.

---

## Follow-on (next plans in this milestone series)

- **M-B**: Holt-Winters forecaster + prediction intervals (consumes the demand structure from M-A).
- **M-C**: forecast-residual + CUSUM detectors (the weather floods from M-A2 feed the kept `RuleDetector`; the demand structure feeds the new statistical detectors).
- **M-D**: scoring-policy DecisionEngine.
