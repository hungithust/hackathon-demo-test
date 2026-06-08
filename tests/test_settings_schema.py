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
