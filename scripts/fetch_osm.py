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
