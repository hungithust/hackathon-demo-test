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
