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
