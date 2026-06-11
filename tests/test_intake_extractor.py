import pytest

from fleet.intake.extractor import build_intake_messages, parse_intake, _INTAKE_SCHEMA
from fleet.scenarios import build_sample_state
from fleet.contracts.state import EventType, EventSeverity, EdgeStatus


def test_build_messages_lists_world_and_enums():
    state = build_sample_state()
    system, user = build_intake_messages("xe 3 hong", state)
    assert "vehicle_breakdown" in system and "flooded_area" in system
    assert "V003" in user and "C001" in user          # roster present
    assert "xe 3 hong" in user                         # report text present


def test_parse_splits_multiple_reports():
    state = build_sample_state()
    data = {"reports": [
        {"event_type": "flooded_area", "target_hint": "duong vao C001",
         "severity": "high", "edge_status": "flooded", "flood_level": 0.6},
        {"event_type": "vehicle_breakdown", "target_hint": "xe 3",
         "severity": "high", "confidence": 0.9},
    ]}
    reports = parse_intake(data, state, raw_text="src")
    assert len(reports) == 2
    flood = reports[0]
    assert flood.event_type == EventType.FLOODED_AREA
    assert flood.target == "DEPOT->C001#2"
    assert flood.edge_status == EdgeStatus.FLOODED and flood.flood_level == 0.6
    veh = reports[1]
    assert veh.event_type == EventType.VEHICLE_BREAKDOWN and veh.target == "V003"
    assert veh.confidence == 0.9 and veh.raw_text == "src"


def test_parse_drops_unresolved_target():
    state = build_sample_state()
    data = {"reports": [
        {"event_type": "vehicle_breakdown", "target_hint": "khong ton tai",
         "severity": "low"}]}
    assert parse_intake(data, state, raw_text="") == []


def test_parse_raises_on_bad_enum():
    state = build_sample_state()
    data = {"reports": [
        {"event_type": "not_a_type", "target_hint": "C001", "severity": "low"}]}
    with pytest.raises(ValueError):
        parse_intake(data, state, raw_text="")


def test_schema_enumerates_all_event_types():
    et = _INTAKE_SCHEMA["properties"]["reports"]["items"]["properties"]["event_type"]
    assert set(et["enum"]) == {e.value for e in EventType}
