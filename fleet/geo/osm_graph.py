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
