# Settings UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-app Settings modal to the FastAPI control room so an operator can change any `Settings` env-var (curated core + expandable Advanced); applying rebuilds the simulation on the new settings (world reset).

**Architecture:** A pure metadata module (`config/settings_schema.py`) is the single source of truth for which fields to expose and how to render/re-apply them. The server exposes `GET/POST /api/settings`; POST rebuilds `SimulationController` on merged settings. The frontend renders a modal from that metadata and applies the returned fresh snapshot.

**Tech Stack:** Python 3.12, FastAPI, pytest; React 18 via in-browser Babel (no build step).

Spec: [docs/superpowers/specs/2026-06-08-settings-ui-design.md](../specs/2026-06-08-settings-ui-design.md)

---

## File Structure

- **Create** `config/settings_schema.py` — `FieldSpec`, `CORE_SPECS`, `build_specs`, `current_values`, `apply`. Pure; imports only `config.settings`.
- **Create** `tests/test_settings_schema.py` — schema coverage, type inference, apply round-trip/errors.
- **Modify** `fleet/ui/server.py` — `_overrides`, `_build_settings`, `GET/POST /api/settings`, make `/api/reset` respect overrides.
- **Create** `tests/test_settings_api.py` — endpoint behavior via direct function calls.
- **Modify** `fleet/ui/web/icons.jsx` — add `gear` glyph.
- **Modify** `fleet/ui/web/api.jsx` — `getSettings`/`saveSettings`; surface server error detail.
- **Create** `fleet/ui/web/settings.jsx` — `SettingsField`, `SettingsModal`.
- **Modify** `fleet/ui/web/panels.jsx` — gear button in `SimControls`.
- **Modify** `fleet/ui/web/app.jsx` — modal open state + wiring.
- **Modify** `fleet/ui/web/index.html` — load `settings.jsx`; append modal CSS.

Convention used throughout: **ENV-var name == dataclass field name upper-cased** (verified against `load_settings`).

---

## Task 1: Settings schema metadata module

**Files:**
- Create: `config/settings_schema.py`
- Test: `tests/test_settings_schema.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings_schema.py
import json
import pytest
from dataclasses import fields

from config.settings import Settings, load_settings
from config import settings_schema as ss


def test_specs_cover_every_field_exactly_once():
    names = [s.field for s in ss.build_specs()]
    assert len(names) == len(set(names)), "a field is specced twice"
    assert set(names) == {f.name for f in fields(Settings)}


def test_core_fields_are_not_advanced():
    core = [s for s in ss.build_specs() if not s.advanced]
    assert {s.field for s in core} >= {"routing_engine", "decision_engine", "world"}
    assert all(s.group != "Advanced" for s in core)


def test_type_inference_for_advanced_fields():
    by_field = {s.field: s for s in ss.build_specs()}
    assert by_field["enable_weather"].type == "bool"      # bool default
    assert by_field["solver_time_limit_sec"].type == "number"  # int default
    assert by_field["demand_noise"].type == "number"      # float default
    assert by_field["nim_model"].type == "text"           # str default


def test_apply_overrides_one_field_round_trip():
    s = ss.apply({"ROUTING_ENGINE": "cuopt"}, base_env={})
    assert s.routing_engine == "cuopt"
    assert s.decision_engine == "rule"   # untouched default


def test_apply_serializes_bool_as_one_zero():
    assert ss.apply({"ENABLE_WEATHER": True}, base_env={}).enable_weather is True
    assert ss.apply({"ENABLE_WEATHER": False}, base_env={}).enable_weather is False


def test_apply_bad_number_raises_value_error():
    with pytest.raises(ValueError):
        ss.apply({"SEED": "not-an-int"}, base_env={})


def test_current_values_is_json_safe_and_keyed_by_env():
    vals = ss.current_values(load_settings({}))
    assert vals["ROUTING_ENGINE"] == "cpu"
    json.dumps(vals)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_schema.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'config.settings_schema'`

- [ ] **Step 3: Write the implementation**

```python
# config/settings_schema.py
"""UI metadata for Settings: which fields to expose, how to render them, and how
to re-apply edited values. Single source of truth for the settings panel.
Imports only config.settings — no UI / FastAPI deps, so it stays testable.

Convention: every Settings field maps to an ENV var named field.upper(), exactly
as load_settings reads it."""

import os
from dataclasses import dataclass, fields
from typing import List, Mapping, Optional, Tuple

from config.settings import Settings, load_settings


@dataclass(frozen=True)
class FieldSpec:
    key: str               # ENV-var name, e.g. "ROUTING_ENGINE"
    field: str             # dataclass attr, e.g. "routing_engine"
    label: str
    type: str              # "select" | "number" | "bool" | "text"
    group: str
    advanced: bool = False
    choices: Tuple[str, ...] = ()
    step: str = "any"      # number inputs only
    help: str = ""


CORE_SPECS: List[FieldSpec] = [
    FieldSpec("ROUTING_ENGINE", "routing_engine", "Routing engine", "select",
              "Engines", choices=("cpu", "cuopt"),
              help="cuopt needs CUOPT_ENDPOINT; otherwise falls back to cpu."),
    FieldSpec("DECISION_ENGINE", "decision_engine", "Decision engine", "select",
              "Engines", choices=("rule", "scoring", "claude", "nim"),
              help="claude needs ANTHROPIC_API_KEY; nim needs NIM_ENDPOINT; else rule."),
    FieldSpec("DETECTOR_ENGINE", "detector_engine", "Detector engine", "select",
              "Engines", choices=("rule", "zscore", "residual", "cusum", "layered")),
    FieldSpec("FORECASTER_ENGINE", "forecaster_engine", "Forecaster", "select",
              "Engines", choices=("ewma", "holt")),
    FieldSpec("WORLD", "world", "World", "select", "World & Time",
              choices=("sample", "real"),
              help="real needs data/hcm_drive.graphml + osmnx; else sample."),
    FieldSpec("SEED", "seed", "Random seed", "number", "World & Time", step="1"),
    FieldSpec("TICK_MINUTES", "tick_minutes", "Minutes per tick", "number",
              "World & Time", step="1"),
    FieldSpec("AUTO_APPROVE_DELAY_THRESHOLD_MIN", "auto_approve_delay_threshold_min",
              "Auto-approve delay (min)", "number", "Thresholds",
              help="Reroute/reschedule under this added delay auto-apply."),
    FieldSpec("SLA_CRITICAL_THRESHOLD_MIN", "sla_critical_threshold_min",
              "SLA critical (min)", "number", "Thresholds"),
    FieldSpec("ENABLE_WEATHER", "enable_weather", "Weather + flooding", "bool", "Toggles"),
    FieldSpec("ENABLE_TRAVEL_TIME", "enable_travel_time", "Replay travel time", "bool", "Toggles"),
    FieldSpec("ENABLE_PROACTIVE", "enable_proactive", "Proactive decisions", "bool", "Toggles"),
]

_CORE_FIELDS = {s.field for s in CORE_SPECS}


def _infer_type(value) -> str:
    if isinstance(value, bool):        # bool before int (bool is a subclass)
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


def build_specs(settings_cls=Settings) -> List[FieldSpec]:
    """CORE_SPECS + an auto Advanced spec for every other Settings field."""
    specs = list(CORE_SPECS)
    defaults = settings_cls()
    for f in fields(settings_cls):
        if f.name in _CORE_FIELDS:
            continue
        val = getattr(defaults, f.name)
        is_int = isinstance(val, int) and not isinstance(val, bool)
        specs.append(FieldSpec(
            key=f.name.upper(), field=f.name,
            label=f.name.replace("_", " ").capitalize(),
            type=_infer_type(val), group="Advanced", advanced=True,
            step=("1" if is_int else "any"),
        ))
    return specs


def current_values(settings) -> dict:
    """Current value per spec, keyed by ENV-var name. JSON-safe."""
    return {s.key: getattr(settings, s.field) for s in build_specs()}


def _to_env_str(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def apply(overrides: Mapping[str, object],
          base_env: Optional[Mapping[str, str]] = None) -> Settings:
    """Merge {ENV_VAR: value} over base_env, then rebuild Settings via
    load_settings. Raises ValueError if a value cannot be parsed (bad int/float)."""
    base = dict(os.environ if base_env is None else base_env)
    for k, v in overrides.items():
        base[k] = _to_env_str(v)
    return load_settings(base)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_schema.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add config/settings_schema.py tests/test_settings_schema.py
git commit -m "feat: settings schema metadata (core + advanced, apply)"
```

---

## Task 2: Settings API endpoints

**Files:**
- Modify: `fleet/ui/server.py`
- Test: `tests/test_settings_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings_api.py
import pytest
from fastapi import HTTPException

from fleet.ui import server as S
from fleet.ui.server import SettingsBody, StepBody


def setup_function(_):
    # isolate each test: clear overrides + rebuild the session
    S._overrides = {}
    S._ctrl = S.SimulationController()


def test_get_settings_returns_groups_and_values():
    r = S.get_settings()
    assert r["groups"], "expected at least one group"
    assert r["values"]["ROUTING_ENGINE"] == "cpu"
    # groups carry render metadata
    f0 = r["groups"][0]["fields"][0]
    assert {"key", "label", "type"} <= set(f0)


def test_post_settings_applies_and_resets_world():
    S.post_step(StepBody(n=3))
    snap = S.post_settings(SettingsBody(values={"ROUTING_ENGINE": "cuopt", "SEED": 7}))
    assert snap["sim_tick"] == 0
    vals = S.get_settings()["values"]
    assert vals["ROUTING_ENGINE"] == "cuopt"
    assert vals["SEED"] == 7


def test_post_settings_bad_value_is_400():
    with pytest.raises(HTTPException) as ei:
        S.post_settings(SettingsBody(values={"SEED": "not-int"}))
    assert ei.value.status_code == 400


def test_reset_keeps_applied_overrides():
    S.post_settings(SettingsBody(values={"ROUTING_ENGINE": "cuopt"}))
    S.post_reset()
    assert S.get_settings()["values"]["ROUTING_ENGINE"] == "cuopt"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_settings_api.py -q`
Expected: FAIL with `AttributeError: module 'fleet.ui.server' has no attribute 'get_settings'` (and `_overrides`).

- [ ] **Step 3: Add the import + `_overrides` near the existing `_ctrl` definition**

In `fleet/ui/server.py`, add the import alongside the other intake imports:

```python
from config import settings_schema
```

Immediately after the existing `_ctrl = SimulationController()` line, add:

```python
# Settings overrides applied via the UI ({} == all defaults from os.environ).
_overrides: dict = {}


def _build_settings():
    return settings_schema.apply(_overrides)
```

- [ ] **Step 4: Add the request model next to `StepBody`/`ReportBody`**

```python
class SettingsBody(BaseModel):
    values: dict = {}
```

- [ ] **Step 5: Add the two endpoints (place them just before the `/api/reset` handler)**

```python
@app.get("/api/settings")
def get_settings():
    groups = []
    for s in settings_schema.build_specs():
        g = next((x for x in groups if x["name"] == s.group), None)
        if g is None:
            g = {"name": s.group, "fields": []}
            groups.append(g)
        g["fields"].append({
            "key": s.key, "label": s.label, "type": s.type,
            "choices": list(s.choices), "step": s.step,
            "advanced": s.advanced, "help": s.help,
        })
    return {"groups": groups, "values": settings_schema.current_values(_build_settings())}


@app.post("/api/settings")
def post_settings(body: SettingsBody):
    global _ctrl, _overrides
    merged = {**_overrides, **body.values}
    try:
        new_settings = settings_schema.apply(merged)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _overrides = merged
    _ctrl = SimulationController(settings=new_settings)
    return _ctrl.snapshot()
```

- [ ] **Step 6: Make `/api/reset` respect applied overrides**

Change the existing reset handler body from `_ctrl = SimulationController()` to:

```python
@app.post("/api/reset")
def post_reset():
    global _ctrl
    _ctrl = SimulationController(settings=_build_settings())
    return _ctrl.snapshot()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_settings_api.py -q`
Expected: PASS (4 passed)

- [ ] **Step 8: Run the existing UI/intake tests to confirm no regression**

Run: `python -m pytest tests/test_ui_controller.py tests/test_intake_controller.py -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add fleet/ui/server.py tests/test_settings_api.py
git commit -m "feat: GET/POST /api/settings (apply rebuilds the world)"
```

---

## Task 3: Settings modal frontend

No automated test harness exists for the in-browser JSX; verify by running the server and exercising the endpoint + page. Provide complete code.

**Files:**
- Modify: `fleet/ui/web/icons.jsx`, `fleet/ui/web/api.jsx`, `fleet/ui/web/panels.jsx`, `fleet/ui/web/app.jsx`, `fleet/ui/web/index.html`
- Create: `fleet/ui/web/settings.jsx`

- [ ] **Step 1: Add a `gear` glyph to `icons.jsx`**

In the `paths` object in `fleet/ui/web/icons.jsx`, add this entry under the `// ---- ui ----` group:

```jsx
    gear: <><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/></>,
```

- [ ] **Step 2: Replace the `jpost` helper + extend the `Api` object in `api.jsx`**

Replace the existing `jpost` function in `fleet/ui/web/api.jsx` with this version (surfaces the server's `detail` on errors):

```jsx
async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let detail = "HTTP " + r.status;
    try { const j = await r.json(); if (j && j.detail) detail = j.detail; } catch (e) {}
    throw new Error(detail);
  }
  return r.json();
}
```

Then add two methods inside the `Api` object literal (after `report:`), keeping the trailing comma style:

```jsx
  getSettings:  async () => jget("/api/settings"),
  saveSettings: async (values) => normalize(await jpost("/api/settings", { values })),
```

- [ ] **Step 3: Create `fleet/ui/web/settings.jsx`**

```jsx
// settings.jsx — Settings modal. Edits Settings env-vars and applies them via
// POST /api/settings, which rebuilds the world (reset) on the new settings.

function SettingsField({ f, value, onChange }) {
  const label = (
    <span className="set-label">{f.label}
      {f.help && <i className="set-help" title={f.help}>?</i>}
    </span>
  );
  if (f.type === "bool") {
    return (
      <label className="set-row set-bool">
        {label}
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(f.key, e.target.checked)}/>
      </label>
    );
  }
  let input;
  if (f.type === "select") {
    input = (
      <select value={value} onChange={(e) => onChange(f.key, e.target.value)}>
        {f.choices.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    );
  } else if (f.type === "number") {
    input = <input type="number" step={f.step} value={value}
              onChange={(e) => onChange(f.key, e.target.value === "" ? "" : Number(e.target.value))}/>;
  } else {
    input = <input type="text" value={value} onChange={(e) => onChange(f.key, e.target.value)}/>;
  }
  return <label className="set-row">{label}{input}</label>;
}

function SettingsModal({ open, onClose, onApplied }) {
  const [groups, setGroups] = React.useState(null);
  const [form, setForm] = React.useState({});
  const [base, setBase] = React.useState({});
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);

  React.useEffect(() => {
    if (!open) return;
    setErr(null); setGroups(null);
    Api.getSettings()
      .then((r) => { setGroups(r.groups); setForm(r.values); setBase(r.values); })
      .catch((e) => setErr(String(e.message || e)));
  }, [open]);

  if (!open) return null;
  const onChange = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  const apply = async () => {
    const changed = {};
    Object.keys(form).forEach((k) => { if (form[k] !== base[k]) changed[k] = form[k]; });
    setBusy(true); setErr(null);
    try {
      const snap = await Api.saveSettings(changed);
      onApplied(snap); onClose();
    } catch (e) { setErr(String(e.message || e)); }
    finally { setBusy(false); }
  };

  const core = (groups || []).filter((g) => g.name !== "Advanced");
  const adv = (groups || []).find((g) => g.name === "Advanced");

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-head">
          <Icon name="gear" size={16}/><h2>Settings</h2>
          <button className="btn ghost icon" onClick={onClose}><Icon name="x" size={15}/></button>
        </div>
        <div className="modal-body">
          {err && <div className="set-err">{err}</div>}
          {groups === null ? <div className="set-loading">Loading…</div> : (<>
            {core.map((g) => (
              <div className="set-group" key={g.name}>
                <div className="set-group-title">{g.name}</div>
                {g.fields.map((f) => <SettingsField key={f.key} f={f} value={form[f.key]} onChange={onChange}/>)}
              </div>
            ))}
            {adv && (
              <details className="set-adv">
                <summary>Advanced · {adv.fields.length} settings</summary>
                <div className="set-group">
                  {adv.fields.map((f) => <SettingsField key={f.key} f={f} value={form[f.key]} onChange={onChange}/>)}
                </div>
              </details>
            )}
          </>)}
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn primary" onClick={apply} disabled={busy || groups === null}>
            {busy ? "Restarting…" : "Apply & restart"}
          </button>
        </div>
      </div>
    </div>
  );
}

window.SettingsModal = SettingsModal;
```

- [ ] **Step 4: Add a gear button to `SimControls` in `panels.jsx`**

Change the `SimControls` signature to accept `onOpenSettings`:

```jsx
function SimControls({ playing, speed, onPlay, onStep, onReset, onSpeed, onOpenSettings }) {
```

Then add this button as the last child, right after the Reset button:

```jsx
      <button className="btn ghost icon" onClick={onOpenSettings} title="Settings"><Icon name="gear" size={15}/></button>
```

- [ ] **Step 5: Wire the modal into `app.jsx`**

Add a state hook with the other `useState` calls:

```jsx
  const [settingsOpen, setSettingsOpen] = React.useState(false);
```

Pass `onOpenSettings` to `SimControls` (extend its existing props):

```jsx
        <SimControls playing={playing} speed={speed}
          onPlay={() => setPlaying((p) => !p)} onStep={doStep} onReset={doReset} onSpeed={setSpeed}
          onOpenSettings={() => setSettingsOpen(true)}/>
```

Add the modal just before the closing `</div>` of the top-level `<div className="app">` (after the `</div>` that closes `.workspace`):

```jsx
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)}
        onApplied={(snap) => { setPlaying(false); apply(snap); }}/>
```

- [ ] **Step 6: Load `settings.jsx` in `index.html`**

In `fleet/ui/web/index.html`, add the script tag right before the `app.jsx` line:

```html
<script type="text/babel" src="settings.jsx"></script>
```

- [ ] **Step 7: Append modal CSS to the `<style>` block in `index.html`**

Add just before the closing `</style>` tag:

```css
/* ============ SETTINGS MODAL ============ */
.modal-backdrop{position:fixed;inset:0;background:rgba(4,7,12,.66);backdrop-filter:blur(3px);display:grid;place-items:center;z-index:50;}
.modal{width:min(620px,92vw);max-height:86vh;display:flex;flex-direction:column;background:linear-gradient(180deg,var(--panel-2),var(--panel));border:1px solid var(--border-strong);border-radius:var(--r-lg);box-shadow:var(--shadow-lg);}
.modal-head{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--border-soft);}
.modal-head h2{font-size:13px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--text-2);margin:0;}
.modal-head .btn.icon{margin-left:auto;}
.modal-body{overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:16px;}
.modal-foot{display:flex;justify-content:flex-end;gap:9px;padding:13px 16px;border-top:1px solid var(--border-soft);}
.set-group-title{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--text-3);font-weight:600;margin-bottom:9px;}
.set-row{display:flex;align-items:center;gap:12px;justify-content:space-between;padding:6px 0;}
.set-label{font-size:13px;color:var(--text);display:flex;align-items:center;gap:6px;}
.set-help{font-style:normal;width:15px;height:15px;border-radius:50%;border:1px solid var(--border-strong);color:var(--text-3);font-size:10px;display:inline-grid;place-items:center;cursor:help;}
.set-row select,.set-row input[type=number],.set-row input[type=text]{width:200px;background:var(--bg-2);border:1px solid var(--border);color:var(--text);border-radius:7px;padding:7px 9px;font-family:var(--sans);font-size:13px;}
.set-row input[type=number]{font-family:var(--mono);}
.set-bool input{width:18px;height:18px;}
.set-adv summary{cursor:pointer;font-size:12px;color:var(--text-2);padding:9px 0;border-top:1px solid var(--border-soft);}
.set-err{background:var(--sev-critical-bg);border:1px solid rgba(255,77,94,.5);color:#FF8088;border-radius:8px;padding:9px 12px;font-size:12px;}
.set-loading{color:var(--text-3);font-size:13px;padding:20px;text-align:center;}
```

- [ ] **Step 8: Smoke-verify the API + page load**

Run (server in background, then curl):

```bash
python -m fleet.ui.server > /tmp/srv.log 2>&1 &
sleep 4
curl -s -o /dev/null -w "index %{http_code}\n" http://127.0.0.1:8000/
curl -s -o /dev/null -w "settings.jsx %{http_code}\n" http://127.0.0.1:8000/settings.jsx
curl -s http://127.0.0.1:8000/api/settings -w "\nsettings %{http_code}\n" | python -c "import sys,json; t=sys.stdin.read(); print('groups:', [g['name'] for g in json.loads(t.rsplit('settings',1)[0])['groups']])"
curl -s -X POST http://127.0.0.1:8000/api/settings -H 'Content-Type: application/json' -d '{"values":{"FORECASTER_ENGINE":"holt"}}' -w "\napply %{http_code}\n" | tail -1
kill %1 2>/dev/null
```

Expected: `index 200`, `settings.jsx 200`, `groups: ['Engines', 'World & Time', 'Thresholds', 'Toggles', 'Advanced']`, `apply 200`.

- [ ] **Step 9: Open the page in a browser and confirm interactively**

Run: `python -m fleet.ui.server` and open http://127.0.0.1:8000. Click the ⚙ gear in the header → modal opens with the four core groups and a collapsed **Advanced**. Change Forecaster to `holt`, click **Apply & restart** → modal closes, Sim Tick resets to `000`, playing is paused. Re-open the modal → Forecaster shows `holt`.

- [ ] **Step 10: Commit**

```bash
git add fleet/ui/web/icons.jsx fleet/ui/web/api.jsx fleet/ui/web/settings.jsx fleet/ui/web/panels.jsx fleet/ui/web/app.jsx fleet/ui/web/index.html
git commit -m "feat: settings modal in the control room UI"
```

---

## Task 4: Full regression

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS (all previous tests + 11 new = green; was 292, expect 303).

- [ ] **Step 2: Commit if anything was adjusted** (otherwise skip)

```bash
git commit -am "test: settings UI regression green"
```

---

## Self-Review notes

- **Spec coverage:** schema module (Task 1) ↔ spec §Architecture/1; endpoints + reset-respects-overrides (Task 2) ↔ §Architecture/2 + §Data flow; modal/gear/api/app/css (Task 3) ↔ §Architecture/3; error→400 + inline (Tasks 2 & 3) ↔ §Error handling; tests ↔ §Testing.
- **Type consistency:** `FieldSpec` fields (`key/field/label/type/group/advanced/choices/step/help`) are produced in Task 1 and consumed identically by the server (`get_settings`, Task 2) and the frontend (`SettingsField`/`SettingsModal`, Task 3). `Api.getSettings` returns raw `{groups,values}`; `Api.saveSettings` returns a normalized snapshot — matching `app.jsx` usage (`onApplied(snap)` → `apply(snap)`).
- **Placeholders:** none — every code step is complete.
