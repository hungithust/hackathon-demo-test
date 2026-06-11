# Real-Map World Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-coded road edges of the sample world with **real** OSM-derived distances, travel times, and route geometry (offline via `osmnx`+`networkx`), expand the roster to ~18 real HCM customers, and render depot/customers/vehicles/routes on a pydeck map — all behind `WORLD=real`, with `build_sample_state` kept as the default fallback.

**Architecture:** A new pure `fleet/geo/` package (router over a networkx graph + a static HCM roster) plus a lazy graph loader. `build_real_state` reuses the existing logical `RoadGraph` shape but fills `RoadEdge` distance/time from real routes and returns a side-car geometry map (kept **outside** `WorldState` so contracts are untouched). The UI controller branches on `WORLD`, falling back to the sample world on any failure; the Streamlit app draws a pydeck map. Everything is gated OFF by default so the 255+ test suite stays green.

**Tech Stack:** Python, existing `fleet.contracts.state` dataclasses, `osmnx>=2.0`/`networkx>=3.0` (lazy-imported, real-map only), `pydeck>=0.8` (Streamlit-bundled, imported only in `app.py`).

Spec: `docs/superpowers/specs/2026-06-08-real-map-world-design.md`.

---

## File Structure

- Create `fleet/geo/__init__.py` — package marker.
- Create `fleet/geo/router.py` — `RouteGeometry`, `nearest_node`, `route` (pure, over any networkx graph).
- Create `fleet/geo/roster.py` — `HCM_CUSTOMERS` (~18 real customers, same tuple shape as `cust_specs`).
- Create `fleet/geo/osm_graph.py` — `load_drive_graph(settings)` (lazy osmnx loader + clear missing-file error).
- Create `scripts/fetch_osm.py` — one-time OSM download → `data/hcm_drive.graphml` (the only networked step).
- Modify `fleet/scenarios.py` — add `build_real_state(graph, customers=None, base_time=...)` (sample untouched).
- Modify `config/settings.py` — 3 new fields + env parsing.
- Modify `fleet/ui/controller.py` — branch on `WORLD`, hold `self.geometry`, extend `snapshot()`.
- Modify `fleet/ui/app.py` — pydeck `render_map` (manual smoke only).
- Modify `.gitignore` — `data/*.graphml`, `cache/`.
- Modify `requirements.txt` — optional-dep comment block.
- Create tests: `tests/test_geo_router.py`, `tests/test_geo_roster.py`, `tests/test_geo_osm_graph.py`, `tests/test_scenarios_real.py`, `tests/test_ui_controller_real.py`.

All test/run commands use the project venv: `d:/hackathon/.venv/Scripts/python.exe`.

---

## Task 1: geo package + pure router

Snaps coordinates to the nearest graph node and computes the shortest path's distance, time, and polyline. Pure: works over any networkx graph whose nodes carry `y`/`x` (lat/lng) and whose edges carry `length` (m) and `travel_time` (s). Falls back to a straight line when no path exists, so a bad coordinate never crashes a build.

**Files:**
- Create: `fleet/geo/__init__.py`
- Create: `fleet/geo/router.py`
- Test: `tests/test_geo_router.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_geo_router.py`:

```python
import networkx as nx
import pytest

from fleet.geo.router import RouteGeometry, nearest_node, route


def _line_graph():
    """3 nodes in a row; two edges of 1000 m / 120 s each."""
    g = nx.DiGraph()
    g.add_node(1, y=10.0000, x=106.0000)
    g.add_node(2, y=10.0000, x=106.0010)
    g.add_node(3, y=10.0000, x=106.0020)
    g.add_edge(1, 2, length=1000.0, travel_time=120.0)
    g.add_edge(2, 3, length=1000.0, travel_time=120.0)
    return g


def test_nearest_node_picks_closest():
    g = _line_graph()
    assert nearest_node(g, 10.0000, 106.0019) == 3
    assert nearest_node(g, 10.0000, 106.0001) == 1


def test_route_sums_length_time_and_builds_polyline():
    g = _line_graph()
    r = route(g, (10.0, 106.0), (10.0, 106.0020))
    assert isinstance(r, RouteGeometry)
    assert r.distance_km == pytest.approx(2.0)
    assert r.minutes == pytest.approx(4.0)
    assert r.polyline == [(10.0, 106.0), (10.0, 106.001), (10.0, 106.002)]


def test_route_disconnected_falls_back_to_straight_line():
    g = _line_graph()
    g.add_node(9, y=11.0, x=107.0)            # isolated; no path from the row
    r = route(g, (10.0, 106.0), (11.0, 107.0), urban_speed_kmh=25.0)
    assert len(r.polyline) == 2                # straight line endpoints
    assert r.distance_km > 0 and r.minutes > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_geo_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.geo'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/geo/__init__.py`:

```python
"""Geospatial layer: real OSM-derived routing + HCM roster for the real-map world.
Imported only when WORLD=real; osmnx stays lazy so the default path never needs it."""
```

Create `fleet/geo/router.py`:

```python
"""Pure routing over a networkx graph: snap lat/lng to nearest node, shortest path
by edge `length`, sum `length`/`travel_time`, return the node polyline. No osmnx,
no I/O — testable with a tiny hand-built graph. Straight-line fallback when there
is no path so a bad coordinate degrades gracefully."""

import math
from dataclasses import dataclass
from typing import List, Tuple

import networkx as nx

LatLng = Tuple[float, float]


@dataclass(frozen=True)
class RouteGeometry:
    distance_km: float
    minutes: float
    polyline: List[LatLng]          # [(lat, lng), ...] along the route


def _haversine_km(a: LatLng, b: LatLng) -> float:
    r = 6371.0
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def nearest_node(graph, lat: float, lng: float):
    best, best_d = None, float("inf")
    for n, data in graph.nodes(data=True):
        d = (data["y"] - lat) ** 2 + (data["x"] - lng) ** 2
        if d < best_d:
            best_d, best = d, n
    return best


def _path_metrics(graph, path) -> Tuple[float, float]:
    """Sum length (m) and travel_time (s) along a node path, picking the shortest
    parallel edge in a MultiGraph."""
    length_m = time_s = 0.0
    multi = graph.is_multigraph()
    for u, v in zip(path[:-1], path[1:]):
        if multi:
            data = min(graph[u][v].values(), key=lambda d: d.get("length", 1e18))
        else:
            data = graph[u][v]
        length_m += float(data.get("length", 0.0))
        time_s += float(data.get("travel_time", 0.0))
    return length_m, time_s


def _straight_line(src: LatLng, dst: LatLng, urban_speed_kmh: float) -> RouteGeometry:
    km = _haversine_km(src, dst)
    return RouteGeometry(km, km / urban_speed_kmh * 60.0, [src, dst])


def route(graph, src: LatLng, dst: LatLng,
          urban_speed_kmh: float = 25.0) -> RouteGeometry:
    o, d = nearest_node(graph, *src), nearest_node(graph, *dst)
    if o is None or d is None:
        return _straight_line(src, dst, urban_speed_kmh)
    try:
        path = nx.shortest_path(graph, o, d, weight="length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return _straight_line(src, dst, urban_speed_kmh)
    if len(path) < 2:
        return _straight_line(src, dst, urban_speed_kmh)
    length_m, time_s = _path_metrics(graph, path)
    poly = [(graph.nodes[n]["y"], graph.nodes[n]["x"]) for n in path]
    km = length_m / 1000.0
    minutes = time_s / 60.0 if time_s > 0 else km / urban_speed_kmh * 60.0
    return RouteGeometry(km, minutes, poly)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_geo_router.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add fleet/geo/__init__.py fleet/geo/router.py tests/test_geo_router.py
git commit -m "feat(geo): pure networkx router (nearest-node + shortest path + fallback)"
```

---

## Task 2: HCM customer roster

A static, deterministic list of ~18 real HCM customers in the **same tuple shape** as the existing `cust_specs` in `scenarios.py`: `(id, type, lat, lng, name, orders, priority, tw_start_h, tw_end_h, sla_h)`. Real coordinates spread across central districts so the map looks full and cuOpt has a real load to optimize.

**Files:**
- Create: `fleet/geo/roster.py`
- Test: `tests/test_geo_roster.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_geo_roster.py`:

```python
from fleet.geo.roster import HCM_CUSTOMERS


def test_roster_is_substantial_and_unique():
    assert len(HCM_CUSTOMERS) >= 15
    ids = [c[0] for c in HCM_CUSTOMERS]
    assert len(ids) == len(set(ids))           # unique ids


def test_roster_rows_are_well_formed():
    for cid, ctype, lat, lng, name, orders, prio, tw_s, tw_e, sla_h in HCM_CUSTOMERS:
        assert cid.startswith("C") and isinstance(name, str) and name
        assert 10.6 < lat < 11.0 and 106.5 < lng < 106.9   # within HCM
        assert isinstance(orders, dict) and orders
        assert 1 <= prio <= 4
        assert tw_s < tw_e and sla_h >= tw_e
```

- [ ] **Step 2: Run test to verify it fails**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_geo_roster.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.geo.roster'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/geo/roster.py`:

```python
"""Static, deterministic HCM customer roster for the real-map world. Same tuple
shape as scenarios.cust_specs:
    (id, type, lat, lng, name, orders, priority, tw_start_h, tw_end_h, sla_h)
Real central-HCM coordinates spread across districts; ids stay C001.. so the
flood-prone parallel edge for C001 keeps its meaning."""

HCM_CUSTOMERS = [
    ("C001", "supermarket",       10.8050, 106.6300, "BigC Mien Dong",
     {"SKU001": 10, "SKU002": 5}, 1, 1, 3, 4),
    ("C002", "market",            10.7725, 106.6980, "Cho Ben Thanh",
     {"SKU001": 20}, 2, 1.5, 3.5, 5),
    ("C003", "convenience_store", 10.8150, 106.6150, "MiniMart Le Loi",
     {"SKU002": 15, "SKU003": 8}, 3, 2, 4, 6),
    ("C004", "restaurant",        10.8300, 106.6400, "Nha hang A Chau",
     {"SKU003": 30}, 2, 1.75, 4, 5.5),
    ("C005", "supermarket",       10.7689, 106.6918, "Co.opmart Cong Quynh",
     {"SKU001": 12, "SKU003": 6}, 2, 1, 4, 5),
    ("C006", "mall",              10.7785, 106.7008, "Vincom Dong Khoi",
     {"SKU002": 18}, 1, 2, 5, 6),
    ("C007", "market",            10.7906, 106.6904, "Cho Tan Dinh",
     {"SKU001": 14}, 3, 1.5, 4, 5.5),
    ("C008", "convenience_store", 10.7820, 106.6820, "Circle K Hai Ba Trung",
     {"SKU002": 9}, 4, 2, 6, 7),
    ("C009", "restaurant",        10.8010, 106.6650, "Quan An Ngon Q3",
     {"SKU003": 22}, 2, 1, 3.5, 5),
    ("C010", "supermarket",       10.7960, 106.6780, "Satra Mart Vo Thi Sau",
     {"SKU001": 16, "SKU002": 7}, 2, 2, 5, 6),
    ("C011", "convenience_store", 10.7700, 106.6790, "GS25 Nguyen Cu Trinh",
     {"SKU003": 11}, 3, 1.5, 4.5, 5.5),
    ("C012", "market",            10.7540, 106.6660, "Cho Nguyen Tri Phuong",
     {"SKU001": 25}, 3, 1, 4, 6),
    ("C013", "mall",              10.7830, 106.6940, "Diamond Plaza",
     {"SKU002": 20, "SKU003": 10}, 1, 2, 5, 6),
    ("C014", "restaurant",        10.8120, 106.6520, "Nha hang Hoa Sen",
     {"SKU003": 28}, 2, 1.75, 4, 5.5),
    ("C015", "supermarket",       10.7610, 106.6820, "Bach Hoa Xanh Tran Hung Dao",
     {"SKU001": 13, "SKU002": 6}, 3, 1, 4, 5),
    ("C016", "convenience_store", 10.8240, 106.6260, "FamilyMart Phan Van Tri",
     {"SKU002": 8}, 4, 2, 6, 7),
    ("C017", "market",            10.7880, 106.6620, "Cho Vuon Chuoi",
     {"SKU001": 17}, 3, 1.5, 4, 5.5),
    ("C018", "restaurant",        10.8060, 106.6840, "Nha hang Que Huong",
     {"SKU003": 24}, 2, 1, 3.5, 5),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_geo_roster.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add fleet/geo/roster.py tests/test_geo_roster.py
git commit -m "feat(geo): ~18 real HCM customers roster"
```

---

## Task 3: build_real_state (real edges + side-car geometry)

Builds a `WorldState` with the **same logical structure** as `build_sample_state` (1 depot, 3 vehicles, depot↔every customer edges, plus the flood-prone parallel `DEPOT->C001#2` edge), but fills each edge's `distance_km`/`base_time_minutes` from `router.route(...)` over an injected graph, and returns a side-car `geometry` map (`edge_id -> polyline`) kept **outside** `WorldState`. `build_sample_state` is left untouched.

**Files:**
- Modify: `fleet/scenarios.py`
- Test: `tests/test_scenarios_real.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scenarios_real.py`:

```python
import networkx as nx

from fleet.scenarios import build_real_state
from fleet.contracts.state import WorldState, EdgeStatus


def _fake_graph():
    """Depot + two customers, fully connected with known length/time."""
    g = nx.DiGraph()
    coords = {
        "D": (10.8231, 106.6297),
        "B": (10.8050, 106.6300),   # C001 location
        "M": (10.7725, 106.6980),   # C002 location
    }
    for n, (y, x) in coords.items():
        g.add_node(n, y=y, x=x)
    for a in coords:
        for b in coords:
            if a != b:
                g.add_edge(a, b, length=2000.0, travel_time=300.0)
    return g


_TWO = [
    ("C001", "supermarket", 10.8050, 106.6300, "BigC", {"SKU001": 10}, 1, 1, 3, 4),
    ("C002", "market",      10.7725, 106.6980, "Cho",  {"SKU001": 20}, 2, 1.5, 3.5, 5),
]


def test_build_real_state_returns_state_and_geometry():
    state, geometry = build_real_state(_fake_graph(), customers=_TWO)
    assert isinstance(state, WorldState)
    assert isinstance(geometry, dict) and geometry


def test_real_edges_get_routed_metrics():
    state, geometry = build_real_state(_fake_graph(), customers=_TWO)
    e = state.road_graph.get_edge("DEPOT->C001")
    assert e.distance_km == 2.0 and e.base_time_minutes == 5.0   # 2000 m / 300 s
    assert "DEPOT->C001" in geometry and len(geometry["DEPOT->C001"]) >= 2


def test_real_state_keeps_flood_parallel_edge():
    state, geometry = build_real_state(_fake_graph(), customers=_TWO)
    flood = state.road_graph.get_edge("DEPOT->C001#2")
    assert flood is not None and flood.status == EdgeStatus.FLOODED
    assert flood.flood_level > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_scenarios_real.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_real_state'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/scenarios.py`, add these imports at the top (next to the existing import):

```python
from typing import Dict, List, Optional, Tuple

from fleet.geo.router import route
from fleet.geo.roster import HCM_CUSTOMERS
```

In `fleet/scenarios.py`, append this function (leave `build_sample_state` unchanged):

```python
def build_real_state(graph, customers: Optional[List[tuple]] = None,
                     base_time: datetime = datetime(2026, 6, 4, 6, 0),
                     urban_speed_kmh: float = 25.0,
                     ) -> Tuple[WorldState, Dict[str, List[Tuple[float, float]]]]:
    """Real-map world: same logical structure as build_sample_state, but edge
    distance/time come from routing over `graph` (injected networkx graph) and a
    side-car geometry map (edge_id -> polyline) is returned for the UI. The graph
    is injected so this is testable offline and never forces an OSM load."""
    customers = customers if customers is not None else HCM_CUSTOMERS

    depot_loc = Location(10.8231, 106.6297, "1 Nguyen Hue, Q.1, HCM", "Kho Chinh HCM")
    depot = Depot(
        location=depot_loc,
        inventory={"SKU001": 400, "SKU002": 200, "SKU003": 320},
        opening_time=base_time,
        closing_time=base_time + timedelta(hours=12),
    )

    vehicles = {}
    for i in range(1, 4):
        vid = f"V{i:03d}"
        vehicles[vid] = Vehicle(
            id=vid, capacity_kg=500, pos=depot_loc, current_load_kg=0,
            status=VehicleStatus.AT_DEPOT,
            shift_start=base_time, shift_end=base_time + timedelta(hours=10),
            veh_type="truck", wade_capability=0.3,
        )

    cust_objs = {}
    for cid, ctype, lat, lng, name, orders, prio, tw_s, tw_e, sla_h in customers:
        cust_objs[cid] = CustomerProfile(
            id=cid, type=ctype,
            location=Location(lat, lng, name, name),
            orders=orders,
            time_window=TimeWindow(base_time + timedelta(hours=tw_s),
                                   base_time + timedelta(hours=tw_e)),
            priority=prio,
            sla_deadline=base_time + timedelta(hours=sla_h),
        )

    nodes = {"DEPOT": RoadNode("DEPOT", depot_loc)}
    for cid in cust_objs:
        nodes[cid] = RoadNode(cid, cust_objs[cid].location)

    edges: Dict[str, RoadEdge] = {}
    adjacency: Dict[str, List[str]] = {n: [] for n in nodes}
    geometry: Dict[str, List[Tuple[float, float]]] = {}
    depot_latlng = (depot_loc.lat, depot_loc.lng)

    def _add(a, b, km, mins, poly, **kw):
        e = RoadEdge(a, b, km, mins, **kw)
        edges[e.id] = e
        adjacency[a].append(e.id)
        geometry[e.id] = poly

    # depot <-> every customer, routed both ways (reverse reuses the forward poly).
    for cid, c in cust_objs.items():
        r = route(graph, depot_latlng, (c.location.lat, c.location.lng),
                  urban_speed_kmh=urban_speed_kmh)
        _add("DEPOT", cid, r.distance_km, r.minutes, r.polyline)
        _add(cid, "DEPOT", r.distance_km, r.minutes, list(reversed(r.polyline)))

    # Flood-prone parallel DEPOT<->C001 route (spec §6.9): shorter but FLOODED, so
    # standard trucks (wade 0.3 m) cannot use it while flooded — keeps M3's
    # per-veh_type matrix logic exercised. Geometry reuses the primary route.
    if "C001" in cust_objs:
        base = edges["DEPOT->C001"]
        poly = geometry["DEPOT->C001"]
        _add("DEPOT", "C001", base.distance_km * 0.6, base.base_time_minutes * 0.6,
             poly, id="DEPOT->C001#2", status=EdgeStatus.FLOODED, flood_level=0.5)
        _add("C001", "DEPOT", base.distance_km * 0.6, base.base_time_minutes * 0.6,
             list(reversed(poly)), id="C001->DEPOT#2",
             status=EdgeStatus.FLOODED, flood_level=0.5)

    state = WorldState(
        clock=base_time,
        depot=depot,
        customers=cust_objs,
        vehicles=vehicles,
        road_graph=RoadGraph(nodes=nodes, edges=edges, adjacency=adjacency),
    )
    return state, geometry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_scenarios_real.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full suite to confirm the sample world is unchanged**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest -q`
Expected: all prior tests still pass plus the new geo/scenario tests.

- [ ] **Step 6: Commit**

```bash
git add fleet/scenarios.py tests/test_scenarios_real.py
git commit -m "feat(geo): build_real_state with routed edges + side-car geometry"
```

---

## Task 4: settings + lazy graph loader + fetch script

Add the 3 real-map settings (all defaulting to the OFF / sample path), a lazy `load_drive_graph` that gives a clear error when the cached graph is missing (without importing osmnx until needed), the one-time fetch script, and the git-ignore / requirements housekeeping.

**Files:**
- Modify: `config/settings.py`
- Create: `fleet/geo/osm_graph.py`
- Create: `scripts/fetch_osm.py`
- Modify: `.gitignore`
- Modify: `requirements.txt`
- Test: `tests/test_geo_osm_graph.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_geo_osm_graph.py`:

```python
import pytest

from config.settings import load_settings
from fleet.geo.osm_graph import load_drive_graph


def test_world_settings_default_to_sample():
    s = load_settings({})
    assert s.world == "sample"
    assert s.osm_graphml_path.endswith(".graphml")
    assert s.urban_speed_kmh > 0


def test_load_drive_graph_missing_file_raises_clear_error():
    s = load_settings({"OSM_GRAPHML_PATH": "data/does_not_exist.graphml"})
    with pytest.raises(FileNotFoundError) as exc:
        load_drive_graph(s)
    assert "fetch_osm" in str(exc.value)        # points the user at the script
```

- [ ] **Step 2: Run test to verify it fails**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_geo_osm_graph.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.geo.osm_graph'` (and an AttributeError on `s.world`).

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add these fields to the `Settings` dataclass (after `intake_extractor`):

```python
    world: str = "sample"                        # real-map: sample | real
    osm_graphml_path: str = "data/hcm_drive.graphml"  # real-map: cached OSM graph
    urban_speed_kmh: float = 25.0                # real-map: conservative travel-time speed
```

In `config/settings.py`, add these to the `return Settings(...)` call in `load_settings` (after `intake_extractor=...`):

```python
        world=e.get("WORLD", "sample"),
        osm_graphml_path=e.get("OSM_GRAPHML_PATH", "data/hcm_drive.graphml"),
        urban_speed_kmh=float(e.get("URBAN_SPEED_KMH", "25.0")),
```

Create `fleet/geo/osm_graph.py`:

```python
"""Lazy loader for the cached OSM drive graph. osmnx is imported only when a graph
is actually loaded, so the test suite and the WORLD=sample path never import it.
The graphml is produced once by scripts/fetch_osm.py and git-ignored."""

import os


def load_drive_graph(settings):
    """Load the cached HCM drive graph. Raises FileNotFoundError (pointing at the
    fetch script) when the cache is missing, so the caller can fall back."""
    path = getattr(settings, "osm_graphml_path", "") or "data/hcm_drive.graphml"
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"OSM graph not found at {path!r}. Run scripts/fetch_osm.py once "
            "(needs internet) to build it, or set WORLD=sample.")
    import osmnx as ox          # optional dep, lazy
    return ox.load_graphml(path)
```

Create `scripts/fetch_osm.py`:

```python
"""One-time fetch of the HCM drive network covering the depot + roster, with
edge speeds clamped to a conservative urban cap (raw OSM maxspeed is highway-fast),
saved to the cached graphml. The ONLY networked step; re-runnable.

Usage:
    python scripts/fetch_osm.py            # -> data/hcm_drive.graphml
"""

import math
import os

import osmnx as ox

from fleet.geo.roster import HCM_CUSTOMERS
from config.settings import load_settings

_DEPOT = (10.8231, 106.6297)


def _haversine_km(a, b):
    r = 6371.0
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def main():
    settings = load_settings()
    speed = settings.urban_speed_kmh
    out = settings.osm_graphml_path
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    far_km = max(_haversine_km(_DEPOT, (c[2], c[3])) for c in HCM_CUSTOMERS)
    dist_m = int(far_km * 1000) + 2000        # buffer so all stops are inside

    print(f"Downloading HCM drive graph: center={_DEPOT} dist={dist_m} m ...")
    g = ox.graph_from_point(_DEPOT, dist=dist_m, network_type="drive",
                            dist_type="bbox")
    g = ox.add_edge_speeds(g, fallback=speed)
    for _u, _v, data in g.edges(data=True):   # clamp to conservative urban speed
        data["speed_kph"] = min(float(data.get("speed_kph", speed)), speed)
    g = ox.add_edge_travel_times(g)

    ox.save_graphml(g, out)
    size_mb = os.path.getsize(out) / 1e6
    print(f"Saved {out}: {len(g.nodes)} nodes, {len(g.edges)} edges, {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
```

In `.gitignore`, add under the runtime-artifacts section:

```text
# real-map world (regenerate via scripts/fetch_osm.py — never commit the graph)
data/*.graphml
cache/
```

In `requirements.txt`, append:

```text
# --- real-map world (optional, lazy-imported; only for WORLD=real) ---
# osmnx>=2.0       # OSM drive graph download + load
# networkx>=3.0    # shortest-path routing over the graph
# pydeck>=0.8      # map rendering (bundled with streamlit)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_geo_osm_graph.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest -q`
Expected: all green (suite never imports osmnx — the missing-file path returns before the import).

- [ ] **Step 6: Commit**

```bash
git add config/settings.py fleet/geo/osm_graph.py scripts/fetch_osm.py .gitignore requirements.txt tests/test_geo_osm_graph.py
git commit -m "feat(geo): WORLD settings + lazy graph loader + fetch_osm script"
```

---

## Task 5: controller branch + snapshot geometry

`SimulationController` branches on `settings.world`: for `real`, load the cached graph and build the real world, falling back to the sample world on any failure (missing graph, osmnx absent). It holds `self.geometry` and extends `snapshot()` with `depot`, `customers`, and `routes` (pydeck-ready `[lng, lat]` paths). `depot`/`customers` come from `state`, so they appear in both worlds; `routes` is populated only when geometry exists.

**Files:**
- Modify: `fleet/ui/controller.py`
- Test: `tests/test_ui_controller_real.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui_controller_real.py`:

```python
from config.settings import load_settings
from fleet.ui.controller import SimulationController


def test_real_world_missing_graph_falls_back_to_sample():
    s = load_settings({"WORLD": "real",
                       "OSM_GRAPHML_PATH": "data/nope.graphml"})
    ctrl = SimulationController(settings=s)      # must NOT raise
    assert ctrl.geometry == {}
    snap = ctrl.snapshot()
    assert snap["vehicles"]                      # sample world still loaded
    assert snap["routes"] == []                  # no geometry -> empty routes


def test_snapshot_exposes_depot_and_customers():
    ctrl = SimulationController()                # default sample world
    snap = ctrl.snapshot()
    assert snap["depot"]["lat"] and snap["depot"]["lng"]
    assert len(snap["customers"]) >= 1
    c0 = snap["customers"][0]
    assert {"id", "lat", "lng", "name", "priority"} <= set(c0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_ui_controller_real.py -v`
Expected: FAIL with `AttributeError: 'SimulationController' object has no attribute 'geometry'`

- [ ] **Step 3: Write minimal implementation**

In `fleet/ui/controller.py`, replace the import line and `__init__` with:

```python
from fleet.scenarios import build_sample_state, build_real_state
```

(keep the other existing imports), and replace `__init__`:

```python
    def __init__(self, state=None, settings=None):
        self.settings = settings or load_settings()
        self.geometry = {}
        if state is not None:
            self.state = state
        elif getattr(self.settings, "world", "sample") == "real":
            self.state = self._load_real_world()
        else:
            self.state = build_sample_state()
        self.components = build_components(self.settings)

    def _load_real_world(self):
        """Build the real-map world, falling back to the sample world (and leaving
        geometry empty) if the OSM graph or osmnx is unavailable."""
        try:
            from fleet.geo.osm_graph import load_drive_graph
            graph = load_drive_graph(self.settings)
            state, geometry = build_real_state(
                graph, urban_speed_kmh=self.settings.urban_speed_kmh)
            self.geometry = geometry
            return state
        except Exception as exc:        # missing graphml / osmnx / bad data
            print(f"[controller] real world unavailable ({exc}); using sample world")
            self.geometry = {}
            return build_sample_state()
```

In `fleet/ui/controller.py`, add these three keys to the dict returned by `snapshot()` (alongside the existing keys):

```python
            "depot": {"lat": s.depot.location.lat, "lng": s.depot.location.lng,
                      "name": s.depot.location.name},
            "customers": [
                {"id": c.id, "lat": c.location.lat, "lng": c.location.lng,
                 "name": c.location.name, "priority": c.priority}
                for c in s.customers.values()
            ],
            "routes": [
                {"edge_id": eid, "path": [[lng, lat] for (lat, lng) in poly]}
                for eid, poly in self.geometry.items()
            ],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest tests/test_ui_controller_real.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite (snapshot key additions must not regress)**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest -q`
Expected: all green. If an existing controller test asserts an exact snapshot key set, update that test to include the three additive keys (the keys are purely additive; do not remove existing ones).

- [ ] **Step 6: Commit**

```bash
git add fleet/ui/controller.py tests/test_ui_controller_real.py
git commit -m "feat(geo): controller WORLD=real branch + snapshot depot/customers/routes"
```

---

## Task 6: pydeck map panel + manual smoke

Replace the bare `st.map` with a pydeck map that draws real route polylines plus depot/customer/vehicle markers. pydeck is imported **only** in `app.py`, so tests never import it. This task is **manual smoke only**.

**Files:**
- Modify: `fleet/ui/app.py`

- [ ] **Step 1: Add the pydeck map renderer**

In `fleet/ui/app.py`, add `import pydeck as pdk` near the top (after `import streamlit as st`), and add this function:

```python
def render_map(snap) -> None:
    depot = snap["depot"]
    view = pdk.ViewState(latitude=depot["lat"], longitude=depot["lng"],
                         zoom=12, pitch=0)
    layers = []
    if snap["routes"]:
        layers.append(pdk.Layer(
            "PathLayer", data=snap["routes"], get_path="path",
            get_color=[30, 120, 220], width_min_pixels=3, pickable=True))
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=[{"position": [depot["lng"], depot["lat"]], "name": depot["name"]}],
        get_position="position", get_fill_color=[240, 190, 20],
        get_radius=180, pickable=True))
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=[{"position": [c["lng"], c["lat"]], "name": c["name"]}
              for c in snap["customers"]],
        get_position="position", get_fill_color=[30, 130, 230],
        get_radius=110, pickable=True))
    layers.append(pdk.Layer(
        "ScatterplotLayer",
        data=[{"position": [v["lng"], v["lat"]], "name": v["id"]}
              for v in snap["vehicles"]],
        get_position="position", get_fill_color=[220, 50, 50],
        get_radius=90, pickable=True))
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view,
                             tooltip={"text": "{name}"}))
```

In `fleet/ui/app.py`, replace the existing vehicles-map block:

```python
    # --- vehicles map + table ---
    st.subheader("Vehicles")
    veh = snap["vehicles"]
    if veh:
        st.map([{"lat": v["lat"], "lon": v["lng"]} for v in veh])
        st.dataframe(veh, use_container_width=True)
```

with:

```python
    # --- map: real routes + depot/customers/vehicles ---
    st.subheader("Bản đồ")
    render_map(snap)
    veh = snap["vehicles"]
    if veh:
        st.dataframe(veh, use_container_width=True)
```

- [ ] **Step 2: Manual smoke (sample world — no OSM needed)**

Run: `d:/hackathon/.venv/Scripts/python.exe -m streamlit run fleet/ui/app.py`
Expected: the app loads; the "Bản đồ" panel shows a pydeck map with the depot (gold), customer markers (blue), and vehicle markers (red). No route polylines yet (sample world), confirming graceful rendering without geometry.

- [ ] **Step 3: Manual smoke (real world — optional, needs the fetched graph)**

Run once to build the graph (needs internet):
`d:/hackathon/.venv/Scripts/python.exe scripts/fetch_osm.py`
Then:
`set WORLD=real` (PowerShell: `$env:WORLD="real"`) and
`d:/hackathon/.venv/Scripts/python.exe -m streamlit run fleet/ui/app.py`
Expected: the map now draws **real route polylines** between the depot and the ~18 customers; markers spread across HCM districts. With the graph missing it silently falls back to the sample world (Task 5).

- [ ] **Step 4: Run the full suite (must not import pydeck)**

Run: `d:/hackathon/.venv/Scripts/python.exe -m pytest -q`
Expected: all green; the suite never imports pydeck (map code lives only in `app.py`).

- [ ] **Step 5: Commit**

```bash
git add fleet/ui/app.py
git commit -m "feat(geo): pydeck map (real routes + depot/customers/vehicles)"
```

---

## Definition of Done

- `d:/hackathon/.venv/Scripts/python.exe -m pytest -q` is green: existing suite plus new geo/scenario/controller tests, with no test importing osmnx or pydeck.
- Default path unchanged: with no `WORLD` env var, the system builds `build_sample_state` exactly as before; `snapshot()` gains additive `depot`/`customers`/`routes` keys (`routes == []`).
- `WORLD=real` with a cached graph builds ~18 real HCM customers, real routed edge distances/times, and route polylines visible on the pydeck map; with the graph missing it falls back to the sample world without raising.
- The graphml is never committed (git-ignored); `scripts/fetch_osm.py` regenerates it (documented for node-07).

## Notes for the executor

- **Run the one-time fetch on your machine first** if you want to smoke the real world: `python scripts/fetch_osm.py` (needs internet; ~tens of seconds; produces a git-ignored `data/hcm_drive.graphml`). On node-07, run the same script (or copy the graphml across) — it needs outbound internet to OpenStreetMap.
- **Speed clamp matters:** raw OSM maxspeed yields unrealistically fast times (measured 2.8 min for 2.67 km). `fetch_osm.py` clamps every edge to `URBAN_SPEED_KMH` (default 25) so cuOpt/OR-Tools see realistic urban times. Tune via the env var, then re-fetch.
- Keep the feature OFF by default; never change `RoadEdge`/`RoadGraph`/`WorldState` or the matrix/simulator/detector signatures — OSM only fills existing fields + a side-car geometry map.
- A runbook entry (org-machine `fetch_osm` command + how to expose the demo port) is a good follow-up once this is green, matching the existing runbook habit.
```
