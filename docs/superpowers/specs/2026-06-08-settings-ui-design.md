# Settings UI — Design Spec

_2026-06-08 · branch `feat/base-project`_

## Problem

Every module knob lives in the `Settings` dataclass ([config/settings.py](../../../config/settings.py),
~50 fields). Today the only ways to change them are: edit the dataclass defaults,
or export environment variables before launching. The new FastAPI control room
([fleet/ui/server.py](../../../fleet/ui/server.py)) always runs on defaults — an
operator has no in-app way to switch the routing/decision engine, the world, or
tune thresholds. We want an in-app **Settings** panel.

## Decisions (locked)

1. **Scope:** a curated *core* set with rich controls, plus an expandable
   *Advanced* section that covers **every remaining** `Settings` field.
2. **Apply semantics:** `Apply` rebuilds `SimulationController` on the new
   settings — i.e. it **resets the world** (tick → 0). The button reads
   **"Apply & restart"**. No mid-run hot-swapping.
3. **Placement:** a **modal overlay** opened by a gear (⚙) button in the header
   sim-controls cluster.

## Architecture

Three units, each independently testable:

### 1. `config/settings_schema.py` (new) — metadata, single source of truth

Pure module, imports only `config.settings` (no UI, no FastAPI). Describes how the
UI should render and re-apply settings.

- **`FieldSpec`** (dataclass / dict): `key` (the ENV-var name, e.g. `ROUTING_ENGINE`),
  `field` (dataclass attr name, e.g. `routing_engine`), `label`, `type`
  (`"select" | "number" | "bool" | "text"`), `group`, `advanced` (bool),
  `choices` (list, select only), `step` (number only), `help`.
- **`CORE_SPECS`**: hand-written specs for the curated fields, grouped:
  - **Engines** — `routing_engine` (cpu｜cuopt), `decision_engine`
    (rule｜scoring｜claude｜nim), `detector_engine`
    (rule｜zscore｜residual｜cusum｜layered), `forecaster_engine` (ewma｜holt).
  - **World & Time** — `world` (sample｜real), `seed` (number),
    `tick_minutes` (number).
  - **Thresholds** — `auto_approve_delay_threshold_min` (number),
    `sla_critical_threshold_min` (number).
  - **Toggles** — `enable_weather`, `enable_travel_time`, `enable_proactive` (bool).
- **`build_specs(settings_cls=Settings) -> list[FieldSpec]`**: returns `CORE_SPECS`
  plus an auto-generated spec for **every `Settings` field not already in core**,
  placed in group `Advanced`, with `type` inferred from the field's default:
  `bool → bool`, `int → number(step=1)`, `float → number(step=any)`, `str → text`.
  Guarantees: union of core+advanced keys == all `Settings` fields, each exactly once.
- **`current_values(settings) -> dict[key, value]`**: current value per spec,
  keyed by ENV-var name, JSON-safe.
- **`apply(overrides: dict[key, value], base_env=os.environ) -> Settings`**:
  merges `{ENV_VAR: str(value)}` over the base env and calls
  `load_settings(merged)`. Bools serialize to `"1"/"0"` to match `load_settings`
  parsing. Raises `ValueError` on a value `load_settings` cannot parse
  (bad int/float).

`load_settings` already owns the field→ENV mapping and the parsing, so `apply`
reuses it rather than re-implementing coercion.

### 2. Backend — `fleet/ui/server.py`

- Module-level **`_overrides: dict[str, str]`**, starts empty (empty == all
  defaults from `os.environ`).
- Helper **`_build_settings()`** → `settings_schema.apply(_overrides)`.
- **`GET /api/settings`** → `{ "groups": [...], "values": { key: value } }`
  where `groups` is `build_specs()` shaped as ordered groups
  (`[{name, fields: [FieldSpec...]}]`) and `values` is `current_values` of the
  live settings.
- **`POST /api/settings`** body `{ "values": { KEY: <str|num|bool> } }`:
  1. validate by calling `settings_schema.apply({**_overrides, **incoming})`;
     on `ValueError` → **HTTP 400** `{detail}` (state untouched).
  2. commit: update `_overrides`, rebuild
     `_ctrl = SimulationController(settings=<new>)` (world reset, tick 0).
  3. return the fresh `snapshot()`.
- **`POST /api/reset`** keeps current `_overrides` (reset respects applied settings).

### 3. Frontend — `fleet/ui/web/`

- **`settings.jsx`** (new, loaded before `app.jsx`): `SettingsModal({ open, onClose,
  onApplied })`.
  - On open: `Api.getSettings()` → render groups. Core groups expanded; **Advanced**
    rendered inside a collapsed `<details>`.
  - Controls by `type`: `select` (dropdown of `choices`), `number` (`<input
    type=number step=...>`), `bool` (toggle), `text` (`<input>`). `help` shown as
    a muted hint / title.
  - Footer: **Apply & restart** (primary) + **Cancel**. Backdrop click =
    Cancel. Apply → `Api.saveSettings(dirtyValues)`; on success call
    `onApplied(snapshot)` and close; on 400 show inline error, keep open.
  - Local form state seeded from fetched `values`; only changed keys are sent.
- **`SimControls`** ([panels.jsx](../../../fleet/ui/web/panels.jsx)): add a ⚙ icon
  button that calls `onOpenSettings`.
- **`icons.jsx`**: add a `gear`/`settings` glyph.
- **`api.jsx`**: `Api.getSettings()` (GET), `Api.saveSettings(values)` (POST →
  normalized snapshot; throws with server detail on non-2xx).
- **`app.jsx`**: `settingsOpen` state; pass `onOpenSettings` to `SimControls`;
  render `<SettingsModal>`; `onApplied(snap)` → `setPlaying(false)`, `apply(snap)`.
- **CSS**: modal overlay + dialog styles appended to the `<style>` block in
  `index.html`, reusing existing tokens (`--panel`, `--border`, `.btn`,
  `.toggle-tabs`, etc.).

## Data flow

```
gear ⚙ → open modal → GET /api/settings ──▶ render form (prefilled)
                                              │ user edits
                                              ▼
                        Apply & restart → POST /api/settings {changed}
                                              │
            server: apply(overrides) → rebuild SimulationController (tick 0)
                                              │
                              ◀── fresh snapshot ──┘
                  app: pause + apply(snapshot), close modal
```

## Error handling

- Bad number/enum value → `apply` raises `ValueError` → 400 → inline modal error,
  no state change.
- Selecting an engine whose dependency is absent (e.g. `decision_engine=claude`
  with no `ANTHROPIC_API_KEY`, or `world=real` with no OSM graph): the
  factory/controller **already falls back** silently (rule-based / sample world).
  This is documented in each affected field's `help`; not an error.

## Testing

- **`config/settings_schema.py`**
  - `build_specs()` keys == set of all `Settings` field ENV names, each once
    (core ∪ advanced, no overlap).
  - Type inference: a bool field → `bool`, int → `number`, float → `number`,
    str → `text`.
  - `apply({"ROUTING_ENGINE": "cuopt"})` → `settings.routing_engine == "cuopt"`,
    other fields unchanged (round-trip).
  - `apply({"SEED": "not-an-int"})` raises `ValueError`.
  - `current_values(load_settings({}))` is JSON-serializable.
- **Server** (direct function calls, as in the existing smoke style)
  - `GET /api/settings` returns `groups` and `values`; values match defaults.
  - `POST /api/settings {"values": {"ROUTING_ENGINE": "cuopt", "SEED": 7}}` →
    snapshot `sim_tick == 0`; a subsequent `GET` reflects the new values.
  - `POST` with `{"SEED": "x"}` → `HTTPException(400)`.
  - Existing UI/intake tests stay green (snapshot shape unchanged).

## Out of scope

- Persisting settings to disk / across restarts (in-memory only).
- Per-field "needs restart" vs "live" distinction (everything restarts).
- Auth around the settings endpoint (local single-operator demo).
