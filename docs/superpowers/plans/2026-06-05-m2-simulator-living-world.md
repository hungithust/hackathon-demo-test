# M2 — Simulator "Living World" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the M1 stub simulator into a real one that makes the world *alive* — seasonal+noisy demand, periodic depot restock, and `INVENTORY_SHORTAGE` events with start/resolve lifecycle — deterministically from `settings.seed`.

**Architecture:** `WorldSimulator.tick()` advances time, grows each customer's orders from an hourly seasonal profile + multiplicative noise (seeded RNG), restocks the depot on a fixed cadence, and raises/resolves shortage events when pending demand crosses depot stock. **Vehicle movement is deliberately out of scope** — realistic movement needs shortest-path (M3's `matrix.py`), so it lands in M3 with the solver. Everything stays behind the existing `Simulator` interface, so the loop and factory are untouched.

**Tech Stack:** Python 3.10+, `random.Random` (seeded), dataclasses, pytest. Same repo/venv/branch as before.

---

## Context

- Continues branch **`feat/base-project`**. Builds directly on plan 1 (M0+M1).
- **Independent of the RoadGraph multiple-edges amendment** (`2026-06-05-roadgraph-multiple-edges.md`): that plan touches `state.py`/`scenarios.py`/graph tests; this plan touches `fleet/simulator/engine.py`, `config/settings.py`, new test files, and `tests/test_loop.py`. No overlapping edits — either order works (amendment-first is tidier).
- **Scope decision (confirmed):** M2 = living world, **no vehicle movement**. Movement + route-following move to M3 alongside the matrix + solver.
- Only changes to existing files: `config/settings.py` (+2 fields), `fleet/simulator/engine.py` (rewrite), `tests/test_config.py` (+assertions), `tests/test_loop.py` (harden vs autonomous events). New: `tests/test_demand.py`, `tests/test_restock.py`, `tests/test_shortage.py`.

Environment reminder (Windows / PowerShell): activate venv `.\.venv\Scripts\Activate.ps1`; run tests `pytest -v`; commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Only `git add` the files named in each task.

---

### Task 1: Add M2 settings (`demand_noise`, `restock_interval_min`)

**Files:**
- Modify: `config/settings.py` (`Settings` dataclass + `load_settings`)
- Test: `tests/test_config.py` (extend `test_defaults`, add one env test)

- [ ] **Step 1: Write the failing tests**

In `tests/test_config.py`, add these two assertions at the end of `test_defaults`:
```python
    assert s.demand_noise == 0.3
    assert s.restock_interval_min == 240
```
And append a new test:
```python
def test_m2_env_overrides():
    s = load_settings(env={"DEMAND_NOISE": "0.5", "RESTOCK_INTERVAL_MIN": "60"})
    assert s.demand_noise == 0.5
    assert s.restock_interval_min == 60
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'demand_noise'`.

- [ ] **Step 3: Add the two fields to `Settings`**

In `config/settings.py`, replace:
```python
    auto_approve_delay_threshold_min: float = 15.0   # spec §6.6
    sla_critical_threshold_min: float = 30.0         # spec §6.2
```
with:
```python
    auto_approve_delay_threshold_min: float = 15.0   # spec §6.6
    sla_critical_threshold_min: float = 30.0         # spec §6.2
    demand_noise: float = 0.3                        # M2: demand multiplicative noise (±)
    restock_interval_min: int = 240                  # M2: depot restock cadence (sim minutes)
```

- [ ] **Step 4: Wire them into `load_settings`**

In `config/settings.py`, replace:
```python
        sla_critical_threshold_min=float(
            e.get("SLA_CRITICAL_THRESHOLD_MIN", "30")),
    )
```
with:
```python
        sla_critical_threshold_min=float(
            e.get("SLA_CRITICAL_THRESHOLD_MIN", "30")),
        demand_noise=float(e.get("DEMAND_NOISE", "0.3")),
        restock_interval_min=int(e.get("RESTOCK_INTERVAL_MIN", "240")),
    )
```

- [ ] **Step 5: Run to verify pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (all config tests).

- [ ] **Step 6: Commit**

```powershell
git add config/settings.py tests/test_config.py
git commit -m "feat(config): M2 settings (demand_noise, restock_interval_min)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Demand generation (seasonal + noise, seeded)

**Files:**
- Modify: `fleet/simulator/engine.py` (full rewrite — demand layer)
- Test: `tests/test_demand.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_demand.py`:
```python
from fleet.simulator.engine import WorldSimulator, _seasonal_factor
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def test_demand_accumulates_over_ticks():
    s = build_sample_state()
    sim = WorldSimulator(load_settings())
    before = s.total_orders_pending()
    for _ in range(10):
        sim.tick(s)
    assert s.total_orders_pending() > before


def test_demand_is_deterministic_for_same_seed():
    s1, s2 = build_sample_state(), build_sample_state()
    sim1 = WorldSimulator(load_settings(env={"SEED": "42"}))
    sim2 = WorldSimulator(load_settings(env={"SEED": "42"}))
    for _ in range(10):
        sim1.tick(s1)
        sim2.tick(s2)
    orders1 = {cid: dict(c.orders) for cid, c in s1.customers.items()}
    orders2 = {cid: dict(c.orders) for cid, c in s2.customers.items()}
    assert orders1 == orders2


def test_seasonal_factor_has_morning_and_evening_peaks():
    assert _seasonal_factor(7) > _seasonal_factor(13)    # morning peak > midday
    assert _seasonal_factor(18) > _seasonal_factor(13)   # evening peak > midday
    assert _seasonal_factor(3) < _seasonal_factor(13)    # night quieter than midday
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_demand.py -v`
Expected: FAIL — `ImportError: cannot import name '_seasonal_factor'` (and no demand growth).

- [ ] **Step 3: Rewrite `fleet/simulator/engine.py` with the demand layer**

Replace the entire contents of `fleet/simulator/engine.py` with:
```python
"""Default world simulator (M2: living world — demand, inventory, restock, shortage).

Vehicle MOVEMENT is intentionally NOT here: realistic movement needs shortest-path
(M3's matrix), so it lands in M3 with the solver. M2 makes the world *alive* —
demand grows, depot stock is restocked, shortages surface — so the detector and
agent have something real to react to. Fully deterministic given settings.seed."""

import random
from datetime import timedelta

from fleet.contracts.state import (
    WorldState, Event, EventType, EventSeverity,
)


def _seasonal_factor(hour: int) -> float:
    """Hourly demand multiplier: morning + evening peaks, quiet overnight."""
    if 6 <= hour < 10:
        return 1.6
    if 16 <= hour < 20:
        return 1.4
    if 10 <= hour < 16:
        return 1.0
    return 0.4


_BASE_RATE_PER_HOUR = {
    "supermarket": 8.0,
    "market": 12.0,
    "convenience_store": 4.0,
    "restaurant": 6.0,
}
_DEFAULT_BASE_RATE = 5.0


class WorldSimulator:
    def __init__(self, settings):
        self.settings = settings
        self.rng = random.Random(settings.seed)
        self._evt_seq = 0

    def tick(self, state: WorldState) -> None:
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1
        self._generate_demand(state)

    def inject_event(self, state: WorldState, event_type: EventType,
                     target: str, severity: EventSeverity) -> Event:
        evt = Event(
            id=self._new_event_id(), event_type=event_type, target=target,
            severity=severity, started_at=state.clock,
            description=f"injected {event_type.value} on {target}",
        )
        state.events.append(evt)
        return evt

    def _new_event_id(self) -> str:
        self._evt_seq += 1
        return f"EVT_{self._evt_seq:03d}"

    def _sample_units(self, expected: float) -> int:
        """Stochastic rounding: integer demand whose mean equals `expected`."""
        base = int(expected)
        return base + (1 if self.rng.random() < (expected - base) else 0)

    def _generate_demand(self, state: WorldState) -> None:
        if not state.depot.inventory:
            return
        skus = sorted(state.depot.inventory.keys())
        hours_per_tick = self.settings.tick_minutes / 60.0
        factor = _seasonal_factor(state.clock.hour)
        noise = self.settings.demand_noise
        for c in state.customers.values():
            base = _BASE_RATE_PER_HOUR.get(c.type, _DEFAULT_BASE_RATE)
            expected = base * hours_per_tick * factor
            expected *= self.rng.uniform(1.0 - noise, 1.0 + noise)
            units = self._sample_units(expected)
            if units <= 0:
                continue
            sku = self.rng.choice(skus)
            c.orders[sku] = c.orders.get(sku, 0) + units
```

- [ ] **Step 4: Run to verify pass (and existing simulator tests still pass)**

Run: `pytest tests/test_demand.py tests/test_simulator.py -v`
Expected: PASS. (`tick` still advances clock/counter and `inject_event` still works, so `test_simulator.py` is unaffected.)

- [ ] **Step 5: Commit**

```powershell
git add fleet/simulator/engine.py tests/test_demand.py
git commit -m "feat(simulator): seasonal+noisy demand generation (seeded, deterministic)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Periodic restock + `INVENTORY_SHORTAGE` lifecycle

**Files:**
- Modify: `fleet/simulator/engine.py` (add typing import, module helper, restock + shortage)
- Test: `tests/test_restock.py` (new), `tests/test_shortage.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_restock.py`:
```python
from datetime import datetime, timedelta

from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import WorldState, Depot, Location
from config.settings import load_settings


def _minimal_state(inventory):
    t0 = datetime(2026, 6, 5, 8, 0)
    return WorldState(clock=t0,
                      depot=Depot(Location(0, 0, "", "d"), dict(inventory),
                                  t0, t0 + timedelta(hours=12)))


def test_restock_adds_batch_at_interval():
    s = _minimal_state({"SKUX": 100})
    sim = WorldSimulator(load_settings(env={"TICK_MINUTES": "5",
                                            "RESTOCK_INTERVAL_MIN": "10"}))
    sim.tick(s)                       # +5 min: below interval, no restock
    assert s.depot.inventory["SKUX"] == 100
    sim.tick(s)                       # +10 min total: restock adds the batch (100)
    assert s.depot.inventory["SKUX"] == 200


def test_inventory_never_negative():
    s = _minimal_state({"SKUX": 5})
    sim = WorldSimulator(load_settings())
    for _ in range(20):
        sim.tick(s)
    assert all(q >= 0 for q in s.depot.inventory.values())
```

Create `tests/test_shortage.py`:
```python
from datetime import datetime, timedelta

from fleet.simulator.engine import WorldSimulator
from fleet.contracts.state import (
    WorldState, Depot, Location, CustomerProfile, TimeWindow, EventType,
)
from config.settings import load_settings

_NO_RESTOCK = {"RESTOCK_INTERVAL_MIN": "100000"}


def _state_with_demand(stock, order_qty):
    t0 = datetime(2026, 6, 5, 8, 0)
    cust = CustomerProfile(
        id="C1", type="market", location=Location(0, 0, "", "c"),
        orders={"SKUX": order_qty},
        time_window=TimeWindow(t0, t0 + timedelta(hours=4)))
    return WorldState(
        clock=t0,
        depot=Depot(Location(0, 0, "", "d"), {"SKUX": stock}, t0,
                    t0 + timedelta(hours=12)),
        customers={"C1": cust})


def _active_shortages(state, sku):
    return [e for e in state.events
            if e.event_type == EventType.INVENTORY_SHORTAGE
            and e.target == sku and e.ended_at is None]


def test_shortage_fires_when_demand_exceeds_stock():
    s = _state_with_demand(stock=0, order_qty=50)
    sim = WorldSimulator(load_settings(env=_NO_RESTOCK))
    sim.tick(s)
    active = _active_shortages(s, "SKUX")
    assert len(active) == 1
    assert active[0].metrics["stock"] == 0.0


def test_shortage_not_duplicated_while_active():
    s = _state_with_demand(stock=0, order_qty=50)
    sim = WorldSimulator(load_settings(env=_NO_RESTOCK))
    sim.tick(s)
    sim.tick(s)
    assert len(_active_shortages(s, "SKUX")) == 1


def test_shortage_resolves_when_stock_recovers():
    s = _state_with_demand(stock=0, order_qty=50)
    sim = WorldSimulator(load_settings(env=_NO_RESTOCK))
    sim.tick(s)
    assert len(_active_shortages(s, "SKUX")) == 1
    s.depot.inventory["SKUX"] = 1_000_000          # stock recovers
    sim.tick(s)
    assert _active_shortages(s, "SKUX") == []
    resolved = [e for e in s.events
                if e.event_type == EventType.INVENTORY_SHORTAGE
                and e.ended_at is not None]
    assert len(resolved) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_restock.py tests/test_shortage.py -v`
Expected: FAIL — restock never happens (inventory stays 100) and no shortage events are created.

- [ ] **Step 3: Add the typing import**

In `fleet/simulator/engine.py`, replace:
```python
import random
from datetime import timedelta
```
with:
```python
import random
from datetime import timedelta
from typing import Dict
```

- [ ] **Step 4: Add the pending-demand helper**

In `fleet/simulator/engine.py`, immediately after the line `_DEFAULT_BASE_RATE = 5.0`, add:
```python


def _pending_demand_by_sku(state: WorldState) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for c in state.customers.values():
        for sku, qty in c.orders.items():
            out[sku] = out.get(sku, 0) + qty
    return out
```

- [ ] **Step 5: Extend `__init__` with restock state**

In `fleet/simulator/engine.py`, replace:
```python
    def __init__(self, settings):
        self.settings = settings
        self.rng = random.Random(settings.seed)
        self._evt_seq = 0
```
with:
```python
    def __init__(self, settings):
        self.settings = settings
        self.rng = random.Random(settings.seed)
        self._evt_seq = 0
        self._mins_since_restock = 0
        self._restock_batch = None      # lazily snapshotted on first tick
```

- [ ] **Step 6: Extend `tick` to restock and update shortages**

In `fleet/simulator/engine.py`, replace:
```python
    def tick(self, state: WorldState) -> None:
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1
        self._generate_demand(state)
```
with:
```python
    def tick(self, state: WorldState) -> None:
        state.clock += timedelta(minutes=self.settings.tick_minutes)
        state.sim_tick += 1
        if self._restock_batch is None:
            self._restock_batch = dict(state.depot.inventory)
        self._generate_demand(state)
        self._maybe_restock(state)
        self._update_shortage_events(state)
```

- [ ] **Step 7: Add the restock + shortage methods**

In `fleet/simulator/engine.py`, append these methods to the `WorldSimulator` class (after `_generate_demand`):
```python
    def _maybe_restock(self, state: WorldState) -> None:
        self._mins_since_restock += self.settings.tick_minutes
        if self._mins_since_restock < self.settings.restock_interval_min:
            return
        self._mins_since_restock = 0
        for sku, qty in (self._restock_batch or {}).items():
            state.depot.inventory[sku] = state.depot.inventory.get(sku, 0) + qty

    def _update_shortage_events(self, state: WorldState) -> None:
        pending = _pending_demand_by_sku(state)
        active = {e.target: e for e in state.events
                  if e.event_type == EventType.INVENTORY_SHORTAGE
                  and e.ended_at is None}
        for sku, stock in state.depot.inventory.items():
            demand = pending.get(sku, 0)
            if demand > stock:
                if sku not in active:
                    state.events.append(Event(
                        id=self._new_event_id(),
                        event_type=EventType.INVENTORY_SHORTAGE, target=sku,
                        severity=self._shortage_severity(demand, stock),
                        started_at=state.clock,
                        description=f"shortage SKU {sku}: pending {demand} > stock {stock}",
                        metrics={"pending": float(demand), "stock": float(stock)},
                    ))
            elif sku in active:
                active[sku].ended_at = state.clock

    @staticmethod
    def _shortage_severity(demand: int, stock: int) -> EventSeverity:
        if stock <= 0 or demand >= stock * 2:
            return EventSeverity.CRITICAL
        if demand >= stock * 1.5:
            return EventSeverity.HIGH
        return EventSeverity.MEDIUM
```

- [ ] **Step 8: Run to verify pass + full suite green**

Run: `pytest -q`
Expected: PASS (restock, shortage, demand, simulator, and everything from earlier plans).

- [ ] **Step 9: Commit**

```powershell
git add fleet/simulator/engine.py tests/test_restock.py tests/test_shortage.py
git commit -m "feat(simulator): periodic restock + INVENTORY_SHORTAGE lifecycle" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Loop integration — harden against autonomous events + smoke

**Files:**
- Modify: `tests/test_loop.py` (target injected events by id; add a living-world test)

- [ ] **Step 1: Harden the two event-flow loop tests**

In `tests/test_loop.py`, replace the body of `test_low_severity_event_flows_to_dispatched_decision` from the `comps.simulator.inject_event(...)` line through the end of the function:
```python
    comps.simulator.inject_event(s, EventType.TRAFFIC, "DEPOT->C001",
                                 EventSeverity.LOW)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    assert len(s.decisions) == 1
    d = s.decisions[-1]
    assert d.action == DecisionAction.REROUTE
    assert d.approval_status == ApprovalStatus.APPROVED
    assert d.approved_by == "auto"
    assert d.executed_at is not None
```
with:
```python
    evt = comps.simulator.inject_event(s, EventType.TRAFFIC, "DEPOT->C001",
                                       EventSeverity.LOW)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    # the simulator may raise its own events (shortages); target only ours.
    mine = [d for d in s.decisions if d.event_id == evt.id]
    assert len(mine) == 1
    d = mine[0]
    assert d.action == DecisionAction.REROUTE
    assert d.approval_status == ApprovalStatus.APPROVED
    assert d.approved_by == "auto"
    assert d.executed_at is not None
```
And replace the body of `test_critical_event_is_queued_not_executed` from its `comps.simulator.inject_event(...)` line to the end:
```python
    comps.simulator.inject_event(s, EventType.VEHICLE_BREAKDOWN, "V001",
                                 EventSeverity.CRITICAL)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    d = s.decisions[-1]
    assert d.approval_status == ApprovalStatus.PENDING
    assert d.executed_at is None
    assert d in s.get_pending_decisions()
```
with:
```python
    evt = comps.simulator.inject_event(s, EventType.VEHICLE_BREAKDOWN, "V001",
                                       EventSeverity.CRITICAL)
    run_loop(s, comps, n_ticks=1, settings=settings, logger=_silent)
    mine = [d for d in s.decisions if d.event_id == evt.id]
    assert len(mine) == 1
    d = mine[0]
    assert d.approval_status == ApprovalStatus.PENDING
    assert d.executed_at is None
    assert d in s.get_pending_decisions()
```

- [ ] **Step 2: Add a living-world integration test**

Append to `tests/test_loop.py`:
```python
def test_loop_world_comes_alive_over_many_ticks():
    s = build_sample_state()
    settings = load_settings(env={"TICK_MINUTES": "30",
                                  "RESTOCK_INTERVAL_MIN": "100000"})
    comps = build_components(settings)
    before = s.total_orders_pending()
    run_loop(s, comps, n_ticks=20, settings=settings, logger=_silent)
    assert s.sim_tick == 20
    assert s.total_orders_pending() > before          # demand accrued over the run
```

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: PASS (all tests).

- [ ] **Step 4: Smoke-run the headless loop**

Run (PowerShell, venv active):
```powershell
python -m fleet.loop
```
Expected: 10 ticks of log lines, clock advanced, no traceback. Demand now grows each tick; if pending crosses depot stock an `inventory_shortage` decision (`DEFER`) appears as `QUEUED(approval)`.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_loop.py
git commit -m "test(loop): harden vs autonomous events; living-world integration test" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Definition of done

- `pytest -q` green; new `test_demand.py`, `test_restock.py`, `test_shortage.py` prove demand growth + determinism, restock cadence + non-negative stock, and shortage start/no-dup/resolve.
- Demand is deterministic for a fixed `seed`; depot restocks on `restock_interval_min`; `INVENTORY_SHORTAGE` events carry `ended_at` lifecycle (resolve when stock recovers).
- `python -m fleet.loop` runs the living world headless without traceback; shortage events flow into queued `DEFER` decisions.
- No vehicle movement yet (by design) — that arrives in M3.

**Next plan: M3 — `CpuSolver` (greedy VRPTW) + `fleet/routing/matrix.py` (Dijkstra on the multi-edge graph, per `veh_type`, honoring flood/blocked) + vehicle movement along solved routes; reroute = matrix update + re-solve.** M3 consumes the amendment's `out_edges`/`edges_between` and the parallel flood-prone edge in the sample.
