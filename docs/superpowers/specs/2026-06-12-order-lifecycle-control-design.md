# Order Lifecycle Control — Design Spec

**Date:** 2026-06-12
**Branch:** voice-model
**Status:** Approved for planning

## Goal

Add an admin-driven order lifecycle layer over the existing FleetOps control room:
surface the simulated orders to the UI, let the admin choose which to dispatch
(per-order or all), watch their progress with explicit order↔vehicle linkage, and
review the whole day as a replayable event→decision→event log.

## Hard Constraint

**No new `WorldState` schema fields.** Every lifecycle state is *derived* from data
already present (`CustomerProfile.orders`, `VehicleRoute.stops`, `Stop.actual_arrival`,
`state.events`, `state.events_archive`, `state.decisions`). Intermediate/derived
view-model data (e.g. recorded snapshots, a controller-side timeline) is allowed; new
*base* data fields are not. There is **no new order generation** — these are the same
simulated orders today's Play would deliver; we only surface them for manual control.

## Background (current behavior)

- `run_loop` auto-plans **all** pending orders the moment the world is first stepped
  (`if not state.plan and total_orders_pending > 0: plan_routes(...)`), then vehicles
  deliver everything.
- `build_routing_problem(state, depot_id)` (in `fleet/routing/matrix.py`) builds the
  solver problem over **all** customers with pending orders and **all** non-broken
  vehicles. `plan_routes` overwrites `state.plan` wholesale.
- `snapshot()` (in `fleet/ui/controller.py`) already exposes vehicles (with live
  position, load%, route paths), customers (with a `delivered` flag), events, decisions
  (pending / resolved / auto-handled), depots, waypoints, and road geometry.
- UI (`fleet/ui/web/`) is a 3-column React layout: left `EventList`, center
  `DispatchMap` + `FleetStrip`, right `ApprovalQueue` + `VoicePanel`. State is
  backend-driven: every mutation calls the server and applies the returned snapshot.

## Derived Lifecycle (the core idea)

A customer's order moves through states, each computed from existing data with no flag:

| State | Derivation |
|-------|------------|
| **Inbox** (đơn tới) | `sum(customer.orders.values()) > 0` **and** the customer appears in **no** `VehicleRoute.stops` across `state.plan`. |
| **In progress** (đang giao) | A `Stop` for the customer exists with `actual_arrival is None`. |
| **Delivered** (đã giao) | That `Stop` has `actual_arrival` set. |

A customer is "incoming" precisely until it first gets a stop; once dispatched it has a
stop forever, so demand refills never bounce it back to the inbox. This is robust and
needs no bookkeeping.

**Order unit:** one "đơn hàng" = one customer's pending delivery (one route stop). You
cannot route to half a customer, and `Stop` / `demand_kg` are per-customer. SKU-level
breakdown comes from `customer.orders` and is shown only in the detail view.

---

## Part 1 — Dispatch gating + waves (backend)

**Files:** `fleet/ui/controller.py`, `fleet/routing/matrix.py` (and possibly
`fleet/routing/planner.py` for a merge helper), `fleet/ui/server.py`, `fleet/loop.py`.

### Gating

- Stepping the world no longer auto-plans. Move the "plan if empty" responsibility out
  of the implicit first-step path so nothing is dispatched until the admin acts.
  - Implementation: `run_loop` keeps working for already-planned worlds; the controller
    stops relying on its auto-plan branch (e.g. pass an explicit flag, or ensure the
    branch is a no-op when the admin hasn't dispatched). The headless `run_loop`
    callers (tests, `main()`, benches) must retain today's behavior — gate the change
    behind the controller, not the loop's default.

### Actions (controller methods + endpoints)

- `dispatch_all()` → plan over **all** inbox customers + **all** idle vehicles. With
  nothing dispatched yet this reproduces today's Play-everything path, so **"Giao tất
  cả" ≡ old Play**.
- `dispatch_orders(customer_ids)` → **wave**: build a routing problem restricted to the
  *selected* inbox customers and *idle* vehicles, solve, and **merge** the resulting
  routes into `state.plan` (never overwrite). Vehicles currently running keep their
  routes untouched.
- **Idle vehicle** = `status == AT_DEPOT` and has no route or all its stops are
  delivered (so a vehicle that finished an earlier wave can take a new one).
- Endpoints: `POST /api/dispatch` (body: `{customer_ids: [...]}` or `{all: true}`),
  returning the fresh snapshot, serialized under the existing `_lock`.

### Routing changes

- `build_routing_problem` gains optional `customer_ids` and `vehicle_ids` filters
  (default `None` = current behavior). When set, `locations`/`tasks` use only the listed
  customers and `fleet` uses only the listed vehicles.
- A small merge helper builds routes for the wave and updates `state.plan[vid]` for the
  idle vehicles used, leaving other entries intact. Reuses `_build_plan` shape (Stop
  construction, start/end times) rather than duplicating it.

---

## Part 2 — Incoming Orders inbox (UI, left tab "Đơn tới")

**Files:** `fleet/ui/controller.py` (snapshot), `fleet/ui/web/panels.jsx`,
`fleet/ui/web/app.jsx`, `fleet/ui/web/api.jsx`.

- `snapshot()` gains an `inbox` array. Each row (from `CustomerProfile`): `id`, `name`,
  `type`, `priority`, per-SKU breakdown + total qty, total weight (`demand_kg`), time
  window, `sla_deadline`.
- Left column becomes tabbed: **Sự kiện | Đơn tới | Tiến trình** (the existing
  `EventList` is the first tab).
- Inbox tab: checkbox list sorted by priority, with a priority chip and SLA per row.
  Buttons **"Giao đã chọn"** (→ `dispatch_orders(selected)`) and **"Giao tất cả"**
  (→ `dispatch_all`).
- Clicking a row highlights that customer's marker on the live map.

---

## Part 3 — Order Progress + detail + order↔vehicle linkage (UI, left tab "Tiến trình")

**Files:** `fleet/ui/controller.py` (snapshot), `fleet/ui/web/panels.jsx`,
`fleet/ui/web/map.jsx`, `fleet/ui/web/app.jsx`.

- `snapshot()` gains `orders_in_progress`, derived per dispatched customer:
  - **assigned_vehicle** = the vehicle whose route contains this customer's stop — *this
    is the order↔vehicle link, fully derived from `state.plan`.*
  - sequence position (e.g. "dừng 3/5"), planned vs actual arrival, `demand_kg`, and a
    status: **Đang chờ xe** (stop exists, earlier stops still pending) / **Đang giao**
    (vehicle's current target is this stop) / **Đã giao** (`actual_arrival` set).
- **Click an order →** detail card: SKUs, contact/notes, assigned vehicle id + status +
  load%, route position, and any event/decision touching that vehicle's route. Selecting
  the order sets `selectedVeh` (highlights the vehicle + route on the map) and pulses the
  customer marker.
- **Click a vehicle** (FleetStrip / map) → filters the progress list to that vehicle's
  orders. Linkage is bidirectional, both ends driven by `state.plan`.

---

## Part 4 — Daily Log replay (UI, full-screen overlay)

**Files:** `fleet/ui/controller.py` (timeline recording), `fleet/ui/server.py`
(`/api/daylog`), `fleet/ui/web/` (new overlay component, reuse `DispatchMap`).

- The controller records a `timeline` list. After each step, when the set of active
  events / decisions / their statuses changes versus the previous tick, it appends an
  entry: `{seq, clock, kind: "event"|"decision", ref_id, title, detail, snapshot}` where
  `snapshot` is the existing view-model at that instant. Decisions carry `event_id`, so
  the **event → decision → event** chain reconstructs directly.
- `GET /api/daylog` returns the timeline. In-memory, single day, cleared on
  `/api/reset`.
- Overlay (reuses the `SettingsModal` full-screen pattern, opened from the header):
  - Left: vertical timeline cards (time, type, severity, action, engine, reasoning,
    measured `added_delay_min`).
  - Right: a **mini `DispatchMap` rendered from the selected entry's snapshot** (map
    component in a static/read-only mode — render given a snapshot, no live stepping).
  - Click a node → map jumps to that moment; optional scrubber to auto-advance the day.
- Real map snapshots without pixel screenshotting; entries recorded only at change
  boundaries, not every tick, to bound memory.

---

## Data Flow

```
inbox (derived from customers w/o stops)
  → dispatch_orders / dispatch_all  (filtered solve + merge into state.plan)
  → step()  (run_loop drives the sim: vehicles move, events fire, decisions queue)
  → snapshot()  (inbox / orders_in_progress / delivered all re-derived)
  → Inbox tab + Progress tab + live map (order↔vehicle highlight)
  → timeline recording (change-boundary snapshots)
  → /api/daylog  → full-screen replay overlay
```

## Testing

Pure-Python controller tests (no FastAPI), matching repo convention; reuse existing
world fixtures.

- Lifecycle derivation: a fresh world puts all customers in inbox; after dispatch they
  move to in-progress; after a visited stop they read delivered.
- Wave dispatch merges new routes for idle vehicles and leaves busy vehicles' routes
  byte-identical.
- `dispatch_all()` on a fresh world produces the same plan as today's full
  `plan_routes`.
- Timeline records an event→decision→event chain with correct `event_id` links and a
  snapshot per entry.

## YAGNI Cuts

- No new `WorldState` schema fields.
- No new order generation.
- No pixel screenshotting (mini-map renders from recorded view-model).
- No per-tick snapshot storage (only change boundaries).
- Single in-memory day (cleared on reset); no multi-day persistence.

## Open Items (resolve during planning)

- Exact mechanism for gating `run_loop`'s auto-plan without breaking headless callers.
- Whether the wave merge helper lives in `planner.py` or `controller.py`.
- Mini-map static-render mode: smallest change to `DispatchMap` that lets it render a
  passed-in snapshot instead of the live one.
