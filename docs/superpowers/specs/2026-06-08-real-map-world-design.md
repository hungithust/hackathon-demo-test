# Real-Map World Design

**Status:** Design (brainstormed 2026-06-08). Feasibility verified by a live osmnx
download on the dev machine (see §9).

**Goal:** Replace the hand-coded road edges of `build_sample_state` with **real**
distances, travel times, and route geometry derived from OpenStreetMap (via
`osmnx` + `networkx`, offline after a one-time fetch), expand the roster to ~18
real HCM customers, and render depot/customers/vehicles/routes on a pydeck map.
The synthetic world stays the default fallback; nothing in the existing
contracts, simulator, detector, router, or test suite changes.

**Non-goals:** turn-by-turn navigation, live traffic feeds, geocoding by name
(we use the customers' real lat/lng directly), committing map data to git,
GPU/cuOpt-at-scale work, the KPI/counterfactual layer (separate "direction B"
spec). Image input and anything touching the voice-intake framework are out.

---

## 1. Guiding principle (the invariant)

The world is modelled as a **logical** `RoadGraph`: one `RoadEdge` per
depot↔customer (and customer↔customer) link, keyed by `edge_id`. The simulator,
detectors, the Dijkstra `matrix.py`, OR-Tools/cuOpt, and 255+ tests all iterate
over these logical edges. **We do not turn OSM's thousands of street segments
into `RoadEdge`s** — that would destroy the model.

Instead, OSM only **fills in numbers and adds geometry on the side**:

- Each logical `RoadEdge.distance_km` / `base_time_minutes` is computed from the
  real shortest path between the two endpoints' real coordinates.
- The route **polyline** (list of `(lat, lng)`) is stored **outside**
  `WorldState`, so `fleet/contracts/state.py` is untouched.

Consequence: `matrix.py`, the simulator, detectors, and cuOpt read the same
`RoadEdge` fields they always did — only now the values are real. Default path
(`WORLD=sample`) is byte-for-byte unchanged, so the suite stays green.

---

## 2. New units (each one job, independently testable)

### 2.1 `fleet/geo/osm_graph.py` — graph loading + cache
- `load_drive_graph(settings) -> networkx.MultiDiGraph`
  - Reads `settings.osm_graphml_path` (default `data/hcm_drive.graphml`).
  - If the file exists → `osmnx.load_graphml(path)` (offline, fast).
  - If missing → raise a clear `FileNotFoundError` pointing at
    `scripts/fetch_osm.py` (we do **not** silently hit the network at runtime).
  - `osmnx` is **lazy-imported** inside the function so the test suite and the
    headless `WORLD=sample` path never import it.
- Speeds/times are baked into the graphml at fetch time (see §2.4), so loading
  needs no recomputation.

### 2.2 `fleet/geo/router.py` — pure routing over a graph
The pure, deterministic core — tested with a tiny hand-built networkx graph, no
OSM, no I/O.
- `nearest_node(graph, lat, lng) -> node_id` — manual nearest by squared
  lat/lng distance (avoids the optional `scikit-learn` dep that
  `osmnx.nearest_nodes` requires).
- `route(graph, src_latlng, dst_latlng) -> RouteGeometry` where
  `RouteGeometry = (distance_km: float, minutes: float, polyline: list[tuple[float,float]])`:
  snap both endpoints to nearest nodes → `networkx.shortest_path(weight="length")`
  → sum edge `length` (m→km) and `travel_time` (s→min) → polyline from node
  `(y, x)` coords.
- If no path exists (disconnected) → return a straight-line fallback
  (haversine km, `km / urban_speed_kmh * 60` minutes, 2-point polyline) so a
  bad node never crashes a build.

### 2.3 `fleet/geo/roster.py` — real HCM customer roster
- `HCM_CUSTOMERS`: ~18 customers as plain tuples in the **same shape** as the
  current `cust_specs` in `scenarios.py` (`id, type, lat, lng, name, orders,
  priority, tw_start_h, tw_end_h, sla_h`), with **real HCM coordinates** spread
  across several districts (Q.1, Q.3, Q.5, Bình Thạnh, Phú Nhuận, Tân Bình…).
  Deterministic; no randomness.
- Pure data only — no imports beyond stdlib/contracts.

### 2.4 `scripts/fetch_osm.py` — one-time fetch (offline thereafter)
- Downloads the HCM drive network covering the depot + every roster customer
  (bbox/point+dist large enough to contain all of §2.3), applies
  `add_edge_speeds(fallback=urban_speed_kmh)` **then clamps** edge speeds to a
  conservative urban cap (see §6) and `add_edge_travel_times`, and saves to
  `data/hcm_drive.graphml`.
- Prints node/edge counts and file size. Re-runnable. This is the only step
  that needs the network. **Documented for node-07 re-run** in the runbook.

---

## 3. Wiring into existing modules (additive, gated)

### 3.1 `fleet/scenarios.py`
- Keep `build_sample_state` **exactly as-is** (the fallback / test default).
- Add `build_real_state(graph=None, customers=HCM_CUSTOMERS) -> tuple[WorldState, dict[str, list[tuple[float,float]]]]`:
  - Same structure as `build_sample_state` (depot, vehicles, nodes), but each
    logical edge's `distance_km`/`base_time_minutes` and the returned geometry
    map come from `router.route(...)`.
  - `graph` is **injected** so this is testable with a tiny fake graph and never
    forces an OSM load in tests. When `graph is None`, the caller (controller)
    is responsible for loading it.
  - Preserve the **parallel flood-prone edge** concept (`DEPOT->C001#2`): keep a
    second, shorter route variant flagged `FLOODED` so M3's per-veh_type wade
    logic still has something to exploit. (Geometry can reuse the primary route
    or a slight offset — visual only.)
  - Returns `(state, geometry)` where geometry keys are `edge_id`s. Geometry
    lives outside `WorldState` → contracts untouched.

### 3.2 `config/settings.py`
Add fields (all default to the OFF/sample path):
```
world: str = "sample"                       # WORLD: sample | real
osm_graphml_path: str = "data/hcm_drive.graphml"
urban_speed_kmh: float = 25.0               # conservative cap for travel time
```
Parse the matching env vars in `load_settings`.

### 3.3 `fleet/ui/controller.py` — `SimulationController`
- In `__init__`, branch on `self.settings.world`:
  - `"real"` → `load_drive_graph(settings)` + `build_real_state(graph)`; store
    `self.geometry`. On any failure (missing graphml, import error) → **log a
    warning and fall back** to `build_sample_state()` with `self.geometry = {}`.
  - `"sample"` (default) → `build_sample_state()`, `self.geometry = {}`.
- Add `self.geometry` (edge_id → polyline) and surface it in `snapshot()` as
  `"routes": [{"path": [[lng,lat], ...], "edge_id": ...}]` (pydeck wants
  `[lng, lat]` order), plus `"customers"` and `"depot"` coordinates for layers.
  Keep all existing snapshot keys unchanged.

### 3.4 `fleet/ui/app.py`
- Replace the bare `st.map(...)` with `render_map(snap)` using **pydeck**:
  - `PathLayer` for `snap["routes"]` (real polylines).
  - `ScatterplotLayer`s: depot (gold), customers (blue, sized by priority),
    vehicles (red, from `snap["vehicles"]`).
  - Tooltip with id/status. Initial view centred on the depot.
- pydeck is imported **only** in `app.py` (like streamlit) → tests never import
  it. If `snap["routes"]` is empty (sample/fallback world) the map still renders
  points, degrading gracefully.

---

## 4. Data / config artifacts

- `data/hcm_drive.graphml` — **git-ignored**, regenerated by `scripts/fetch_osm.py`.
- `.gitignore` — add `data/*.graphml` and osmnx's `cache/` directory.
- `requirements.txt` — add an optional, commented block (mirroring the intake
  pattern), since these are lazy-imported and only needed for `WORLD=real`:
  ```
  # --- real-map world (optional; only for WORLD=real) ---
  # osmnx>=2.0       # OSM drive graph + routing
  # networkx>=3.0    # shortest-path over the graph
  # pydeck>=0.8      # map rendering (bundled with streamlit)
  ```

---

## 5. Testing strategy

- `tests/test_geo_router.py` — pure: build a tiny networkx graph by hand,
  assert `nearest_node`, `route` distance/minutes/polyline, and the
  disconnected straight-line fallback. No OSM, no I/O.
- `tests/test_scenarios_real.py` — `build_real_state` with an **injected** tiny
  fake graph covering the depot + a couple of customers: assert edges get real
  (non-default) km/minutes, geometry map keyed by edge_id, parallel flood edge
  preserved, returns `(WorldState, dict)`.
- `tests/test_geo_roster.py` — roster is well-formed (~18 entries, unique ids,
  valid lat/lng ranges, schema matches `cust_specs`).
- Controller fallback test: `WORLD=real` with a missing graphml path →
  `SimulationController` falls back to the sample world without raising.
- The suite must **never import** osmnx or pydeck (lazy-imported only in
  `osm_graph.py` default loader and `app.py`).
- Full suite stays green on the default `WORLD=sample` path.

---

## 6. Known issues found during feasibility (must address in the plan)

- **Travel time too fast from raw OSM maxspeed** (measured 2.8 min for 2.67 km).
  `fetch_osm.py` must **clamp edge speeds** to `urban_speed_kmh` (≈25 km/h)
  rather than trusting OSM maxspeed, so cuOpt/OR-Tools see realistic urban times.
- **graphml size** (~10.8 MB for a 4 km radius; multi-district will be larger) →
  never committed; fetch script + runbook entry instead.
- **`osmnx.nearest_nodes` needs scikit-learn** for an unprojected graph → we use
  a manual nearest-node in `router.py`, no extra dep.
- **osmnx writes a `cache/` dir** on download → git-ignored.

---

## 7. Resources needed (confirmed available)

- `osmnx>=2.0`, `networkx>=3.0`, `pydeck>=0.8` — pip, $0, CPU. **Verified
  installable in `.venv`** (pulls geopandas/shapely/pyproj/pyogrio).
- One-time OSM HCM download (~tens of seconds, needs internet) → produces the
  cached graphml. **Verified working on the dev machine.**
- No GPU, no API key, no node-07, no entitlement.

---

## 8. Degradation guarantees

- `WORLD` unset → `build_sample_state`, exactly today's behaviour.
- `WORLD=real` but graphml/osmnx missing → controller warns and falls back to
  the sample world; the demo still runs.
- Map with no routes → pydeck still renders points.

---

## 9. Feasibility evidence (2026-06-08, dev machine, `.venv`)

- `osmnx 2.1.0` installed into `.venv` alongside networkx 3.6, pydeck 0.8.
- `graph_from_point((10.8231,106.6297), dist=4000, network_type="drive")` →
  8622 nodes / 19629 edges in ~8–18 s.
- Manual nearest-node + `shortest_path(weight="length")` depot→BigC Q.1 →
  **2.67 km, polyline of 33 real points**.
- `save_graphml` → 10.8 MB. (Confirms §6 size + speed-clamp findings.)

---

## 10. Out of scope / future

- KPI counterfactual + decision cards (direction B) — its own spec, can render
  on top of this map.
- cuOpt-at-scale benchmark (direction C, needs GPU/node-07).
- Live traffic, geocoding-by-name, multi-city.
