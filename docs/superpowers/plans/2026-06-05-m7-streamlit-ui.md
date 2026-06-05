# M7 — Streamlit UI (dashboard + human-in-the-loop approval) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the operator-facing UI for the fleet optimizer — a Streamlit dashboard that drives the existing `WorldState` + `run_loop`: step the simulation, watch the world (clock, vehicles, events), and **approve/reject** the decisions the engine queues for a human — without changing any engine code.

**Architecture:** All the logic lives in a thin, **fully-testable** `SimulationController` (`fleet/ui/controller.py`) that wraps `build_sample_state` + `build_components` and exposes `step()`, `approve(id)`, `reject(id)`, and a plain-dict `snapshot()` for rendering. The Streamlit script (`fleet/ui/app.py`) is glue only — it reads the controller's snapshot and wires buttons to controller methods — and is **not** unit-tested (Streamlit isn't imported by the test suite). The controller reuses the exact approval gate and `reroute` re-solve the headless loop already uses, so the UI and the headless loop behave identically.

**Tech Stack:** Python 3.10+, dataclasses, pytest (controller). Streamlit (UI runtime only — imported solely by `app.py`, never by tests). Same repo/venv/branch.

---

## Context

- Continues branch **`feat/base-project`** (plans 1–9: M0–M6 complete & green; 133 passing after M6). **This is the final milestone of the base-project series.**
- Implements M7: "Streamlit UI over the existing `WorldState` + `run_loop`: map/timeline, event feed, pending-decision approval controls."
- **No engine changes.** Everything new is additive: a controller package + a Streamlit app + one requirements line.

**Verified facts from the current code:**
- `run_loop(state, components, n_ticks, settings, logger=print) -> WorldState)` (`fleet/loop.py`): each tick runs `simulator.tick → detector.detect (+ active events) → decision_engine.decide → approval gate (should_auto_approve) → dispatcher.apply for approved`, and re-solves once via `reroute(state, components.optimizer)` when an approved REROUTE fired. Non-auto decisions are left `PENDING`.
- `build_components(settings) -> Components(simulator, detector, optimizer, forecaster, decision_engine, dispatcher)` (`fleet/factory.py`). `build_sample_state()` (`fleet/scenarios.py`) → a populated `WorldState`.
- `WorldState` helpers: `get_pending_decisions()`, `get_approved_decisions()`, `get_active_events()`, `total_orders_pending()`, `.clock` (datetime), `.sim_tick`, `.vehicles: Dict[str, Vehicle]`, `.decisions: List[Decision]`.
- `ApprovalStatus`: `PENDING, APPROVED, REJECTED, OVERRIDE`. `Decision` has `approval_status, approved_by, approved_at, executed_at, impact_estimate, action, event_id, description, id`.
- `Dispatcher.apply(state, decision)` stamps `executed_at` + `execution_result`.
- `reroute(state, optimizer, depot_id="DEPOT") -> List[str]` (`fleet/routing/planner.py`) — re-solves against the live graph.
- `Vehicle` has `id, status (VehicleStatus), pos (Location: lat,lng,address,name), current_stop_index`. `Event` has `id, event_type, target, severity, started_at`.
- All `fleet/<subpkg>/` dirs contain `__init__.py`; `fleet/ui/` must too.

**Design decisions (documented in code):**
- The controller **does not** re-implement the loop's per-tick logic — `step(n)` calls `run_loop(..., logger=<silent>)`. After a step, auto-approvable decisions are already applied; the remainder sit `PENDING` for the operator. `approve`/`reject` act on those.
- `approve(id)` mirrors the loop's approved path exactly: mark `APPROVED` (`approved_by="human"`), `dispatcher.apply`, and if the action is `REROUTE` (and there are pending orders) call `reroute` — so a human-approved reroute re-solves just like an auto-approved one.
- `snapshot()` returns only JSON-friendly primitives (no dataclass instances) so the view layer is trivial and the snapshot is directly assertable in tests.
- `app.py` holds a single `SimulationController` in `st.session_state` across reruns; it imports Streamlit at module top, so it is never imported by the test suite. Streamlit is a UI-only dependency.

**Changes:** new `fleet/ui/__init__.py`, new `fleet/ui/controller.py`, new `tests/test_ui_controller.py`, new `fleet/ui/app.py`, modify `requirements.txt` (+1 line).

Environment reminder (Windows / PowerShell): activate venv `.\.venv\Scripts\Activate.ps1`; run tests `pytest -v`; commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Only `git add` the files named in each task — do NOT touch `Guide.md`, `problem.txt`, `docs/PROBLEM_STATEMENT.md`.

---

### Task 1: `SimulationController` core (init + step + snapshot)

**Files:**
- Create: `fleet/ui/__init__.py`
- Create: `fleet/ui/controller.py`
- Test: new `tests/test_ui_controller.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui_controller.py`:
```python
from fleet.ui.controller import SimulationController


def test_controller_starts_at_tick_zero():
    c = SimulationController()
    snap = c.snapshot()
    assert snap["sim_tick"] == 0
    assert isinstance(snap["clock"], str)            # ISO string, not datetime
    assert snap["vehicles"]                          # sample world has vehicles
    assert "pending_orders" in snap


def test_step_advances_the_world():
    c = SimulationController()
    c.step(3)
    snap = c.snapshot()
    assert snap["sim_tick"] == 3
    # decision counters are present and consistent
    d = snap["decisions"]
    assert d["total"] == d["pending"] + d["approved"] + d["rejected"] + d["other"]


def test_snapshot_is_json_safe():
    import json
    c = SimulationController()
    c.step(1)
    json.dumps(c.snapshot())   # raises if any value isn't JSON-serializable
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ui_controller.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fleet.ui'`.

- [ ] **Step 3: Implement the package + controller core**

Create `fleet/ui/__init__.py` (empty):
```python
```

Create `fleet/ui/controller.py`:
```python
"""UI-facing controller (M7). Wraps the headless simulation so a Streamlit (or any)
front end can drive it without touching engine internals: step the world, read a
JSON-friendly snapshot, and approve/reject queued decisions. Reuses run_loop and
reroute so the UI behaves identically to the headless loop."""

from typing import Dict, List, Optional

from fleet.contracts.state import ApprovalStatus, DecisionAction
from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.routing.planner import reroute
from config.settings import load_settings


def _silent(*_args, **_kwargs):
    pass


class SimulationController:
    def __init__(self, state=None, settings=None):
        self.settings = settings or load_settings()
        self.state = state or build_sample_state()
        self.components = build_components(self.settings)

    # ----- driving the world -----
    def step(self, n_ticks: int = 1):
        from fleet.loop import run_loop
        run_loop(self.state, self.components, max(1, int(n_ticks)),
                 settings=self.settings, logger=_silent)
        return self

    # ----- view model -----
    def snapshot(self) -> Dict:
        s = self.state
        by_status = {st: 0 for st in ("pending", "approved", "rejected", "other")}
        for d in s.decisions:
            key = d.approval_status.value
            by_status[key if key in by_status else "other"] += 1
        return {
            "clock": s.clock.isoformat(),
            "sim_tick": s.sim_tick,
            "pending_orders": s.total_orders_pending(),
            "vehicles": [
                {"id": v.id, "status": v.status.value,
                 "lat": v.pos.lat, "lng": v.pos.lng,
                 "stop_index": v.current_stop_index}
                for v in s.vehicles.values()
            ],
            "active_events": [
                {"id": e.id, "event_type": e.event_type.value,
                 "target": e.target, "severity": e.severity.value}
                for e in s.get_active_events()
            ],
            "decisions": {
                "total": len(s.decisions),
                "pending": by_status["pending"],
                "approved": by_status["approved"],
                "rejected": by_status["rejected"],
                "other": by_status["other"],
            },
            "pending_decisions": [
                {"id": d.id, "action": d.action.value, "event_id": d.event_id,
                 "description": d.description,
                 "added_delay_min": d.impact_estimate.get("added_delay_min", 0.0)}
                for d in s.get_pending_decisions()
            ],
        }
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_ui_controller.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```
git add fleet/ui/__init__.py fleet/ui/controller.py tests/test_ui_controller.py
git commit -m "feat(ui): SimulationController core (step + JSON snapshot)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Approve / reject queued decisions

**Files:**
- Modify: `fleet/ui/controller.py`
- Test: `tests/test_ui_controller.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ui_controller.py`:
```python
from fleet.contracts.state import (
    EventType, EventSeverity, ApprovalStatus, DecisionAction,
)


def _controller_with_pending_decision():
    """A CRITICAL breakdown -> REALLOCATE, which the gate always queues PENDING."""
    c = SimulationController()
    c.components.simulator.inject_event(
        c.state, EventType.VEHICLE_BREAKDOWN, "V001", EventSeverity.CRITICAL)
    c.step(1)
    pend = c.state.get_pending_decisions()
    assert pend, "expected at least one pending decision to approve/reject"
    return c, pend[0]


def test_approve_marks_executed_by_human():
    c, d = _controller_with_pending_decision()
    returned = c.approve(d.id)
    assert returned.approval_status == ApprovalStatus.APPROVED
    assert returned.approved_by == "human"
    assert returned.executed_at is not None
    assert d not in c.state.get_pending_decisions()


def test_reject_marks_rejected_not_executed():
    c, d = _controller_with_pending_decision()
    returned = c.reject(d.id)
    assert returned.approval_status == ApprovalStatus.REJECTED
    assert returned.approved_by == "human"
    assert returned.executed_at is None
    assert d not in c.state.get_pending_decisions()


def test_approve_unknown_id_raises():
    import pytest
    c = SimulationController()
    with pytest.raises(KeyError):
        c.approve("NOPE")


def test_approving_a_reroute_resolves_routes():
    # seed a concrete order so reroute has something to plan
    c = SimulationController()
    c.state.customers["C001"].orders = {"SKUX": 20}
    c.state.depot.inventory["SKUX"] = 200
    # a manual REROUTE decision sitting pending
    from fleet.contracts.state import Decision, DecisionEngine
    d = Decision(id="DEC_MANUAL", timestamp=c.state.clock, event_id=None,
                 action=DecisionAction.REROUTE, engine=DecisionEngine.HUMAN,
                 description="manual reroute", impact_estimate={"added_delay_min": 0.0})
    c.state.decisions.append(d)
    c.approve(d.id)
    assert c.state.plan        # reroute() wrote a fresh plan
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ui_controller.py -v`
Expected: FAIL — `AttributeError: 'SimulationController' object has no attribute 'approve'`.

- [ ] **Step 3: Implement approve/reject**

Append these methods to `SimulationController` in `fleet/ui/controller.py`:
```python
    # ----- human-in-the-loop approval -----
    def approve(self, decision_id: str):
        d = self._find_pending(decision_id)
        d.approval_status = ApprovalStatus.APPROVED
        d.approved_by = "human"
        d.approved_at = self.state.clock
        self.components.dispatcher.apply(self.state, d)
        if (d.action == DecisionAction.REROUTE
                and self.state.total_orders_pending() > 0):
            reroute(self.state, self.components.optimizer)
        return d

    def reject(self, decision_id: str):
        d = self._find_pending(decision_id)
        d.approval_status = ApprovalStatus.REJECTED
        d.approved_by = "human"
        d.approved_at = self.state.clock
        return d

    def _find_pending(self, decision_id: str):
        for d in self.state.get_pending_decisions():
            if d.id == decision_id:
                return d
        raise KeyError(f"no pending decision with id {decision_id!r}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_ui_controller.py -v`
Expected: PASS (all controller tests).

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: still green (controller is additive; no engine code changed).

- [ ] **Step 6: Commit**

```
git add fleet/ui/controller.py tests/test_ui_controller.py
git commit -m "feat(ui): controller approve/reject with REROUTE re-solve

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Streamlit app + dependency

**Files:**
- Create: `fleet/ui/app.py`
- Modify: `requirements.txt`
- Test: `tests/test_ui_controller.py` (append one end-to-end integration test — the app itself is not unit-tested)

- [ ] **Step 1: Write the failing test**

The Streamlit script can't be unit-tested without a running Streamlit server, so the regression guard is an **end-to-end controller flow** that exercises the same sequence the UI buttons drive (step → inspect snapshot → approve a pending decision). Append to `tests/test_ui_controller.py`:
```python
def test_end_to_end_step_then_approve_flow():
    c, d = _controller_with_pending_decision()
    before = c.snapshot()
    assert before["decisions"]["pending"] >= 1
    c.approve(d.id)
    after = c.snapshot()
    assert after["decisions"]["pending"] == before["decisions"]["pending"] - 1
    assert after["decisions"]["approved"] == before["decisions"]["approved"] + 1
    # stepping further keeps the world consistent and JSON-safe
    import json
    c.step(2)
    json.dumps(c.snapshot())
    assert c.snapshot()["sim_tick"] == before["sim_tick"] + 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_ui_controller.py::test_end_to_end_step_then_approve_flow -v`
Expected: FAIL — counts won't line up until the flow is exercised against the implemented `approve` (it should actually PASS already, since approve was built in Task 2). If it passes immediately, that's acceptable here: this task's real deliverable is `app.py`; the test is an integration guard, not a red-then-green driver. Proceed to Step 3.

> TDD note: Tasks 1–2 already drove `approve`/`step` red→green. This task is primarily the (untestable) Streamlit view; the integration test locks the controller flow the view depends on.

- [ ] **Step 3: Write the Streamlit app**

Create `fleet/ui/app.py`:
```python
"""Streamlit dashboard for the delivery-fleet optimizer (M7).

Glue only — all logic is in SimulationController. Run with:
    streamlit run fleet/ui/app.py

Streamlit is imported here and nowhere else, so the headless system and the test
suite never depend on it."""

import streamlit as st

from fleet.ui.controller import SimulationController


def _controller() -> SimulationController:
    if "ctrl" not in st.session_state:
        st.session_state.ctrl = SimulationController()
    return st.session_state.ctrl


def main() -> None:
    st.set_page_config(page_title="Fleet Optimizer", layout="wide")
    st.title("Realtime Delivery-Fleet Optimizer")

    ctrl = _controller()

    # --- controls ---
    c1, c2, c3 = st.columns(3)
    if c1.button("Step 1 tick"):
        ctrl.step(1)
    if c2.button("Step 5 ticks"):
        ctrl.step(5)
    if c3.button("Reset"):
        st.session_state.ctrl = SimulationController()
        ctrl = st.session_state.ctrl

    snap = ctrl.snapshot()

    # --- metrics ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sim tick", snap["sim_tick"])
    m2.metric("Clock", snap["clock"].replace("T", " "))
    m3.metric("Pending orders", snap["pending_orders"])
    m4.metric("Pending decisions", snap["decisions"]["pending"])

    # --- vehicles map + table ---
    st.subheader("Vehicles")
    veh = snap["vehicles"]
    if veh:
        st.map([{"lat": v["lat"], "lon": v["lng"]} for v in veh])
        st.dataframe(veh, use_container_width=True)

    # --- active events ---
    st.subheader("Active events")
    st.dataframe(snap["active_events"] or [{"info": "none"}],
                 use_container_width=True)

    # --- approval queue ---
    st.subheader("Decisions awaiting approval")
    pend = snap["pending_decisions"]
    if not pend:
        st.info("No decisions awaiting approval.")
    for d in pend:
        cols = st.columns([4, 1, 1])
        cols[0].write(
            f"**{d['action']}** — {d['description']} "
            f"(+{d['added_delay_min']} min)")
        if cols[1].button("Approve", key=f"ap_{d['id']}"):
            ctrl.approve(d["id"])
            st.rerun()
        if cols[2].button("Reject", key=f"rj_{d['id']}"):
            ctrl.reject(d["id"])
            st.rerun()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add the dependency**

In `requirements.txt`, append:
```
# UI (M7): Streamlit dashboard. Needed only to run `streamlit run fleet/ui/app.py`;
# the headless system and the test suite do not import it.
streamlit>=1.30
```

- [ ] **Step 5: Run the integration test + full suite + manual smoke**

Run: `pytest tests/test_ui_controller.py -v` → PASS.
Run: `pytest -v` → all green.
Manual smoke (optional, requires `pip install streamlit`): `streamlit run fleet/ui/app.py` — click **Step 5 ticks**, confirm the metrics advance, the vehicle map/table render, and (after injecting/accumulating a non-auto decision) the approval buttons mark it approved/rejected and it leaves the queue. The headless path is unaffected: `python -m fleet.loop` still runs clean.

- [ ] **Step 6: Commit**

```
git add fleet/ui/app.py requirements.txt tests/test_ui_controller.py
git commit -m "feat(ui): Streamlit dashboard with step + approval controls

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Verification checklist (end of plan)

- [ ] `pytest -v` fully green.
- [ ] `SimulationController` constructs from `build_sample_state` + `build_components`, `step(n)` advances `sim_tick` by `n` via `run_loop`, and `snapshot()` is JSON-serializable.
- [ ] `approve(id)` marks `APPROVED`/`approved_by="human"`, dispatches (sets `executed_at`), and re-solves on `REROUTE`; `reject(id)` marks `REJECTED` without executing; unknown id raises `KeyError`.
- [ ] The test suite never imports `streamlit` (only `fleet/ui/app.py` does).
- [ ] `streamlit run fleet/ui/app.py` renders metrics, vehicle map/table, event feed, and working approve/reject buttons; `python -m fleet.loop` still runs clean.
- [ ] Only the files named in each task were committed (no `Guide.md`/`problem.txt`/`docs/PROBLEM_STATEMENT.md`).

**Completes M7 — and the base-project series (M0–M7).** The system now spans contracts → living-world simulator → routing matrix + CPU/cuOpt solvers → vehicle movement/reroute → rule/Claude decision engines → EWMA/z-score forecasting & detection → operator UI, every layer behind a swappable interface chosen by `config/settings.py`. Natural follow-ons (out of series): real Prophet forecaster, a live map with route polylines, persistence/replay of `WorldState` snapshots, and multi-depot support.
