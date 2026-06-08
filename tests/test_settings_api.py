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
