"""Extract-only path: transcribe -> extract -> reports, with no world injection."""

from fleet.intake.pipeline import extract_reports
from fleet.scenarios import build_sample_state
from fleet.contracts.state import EventType


def _fake_complete(reports):
    return lambda system, user: {"reports": reports}


def test_text_extracts_reports_without_touching_world():
    state = build_sample_state()
    raw, reports = extract_reports(
        state,
        _fake_complete([{"event_type": "inventory_shortage",
                         "target_hint": "C001", "severity": "high"}]),
        text="kho C001 het hang")
    assert raw == "kho C001 het hang"
    assert len(reports) == 1
    assert reports[0].event_type == EventType.INVENTORY_SHORTAGE
    assert reports[0].target == "C001"


def test_audio_is_transcribed_then_extracted():
    state = build_sample_state()
    transcriber = type("T", (), {"transcribe": lambda self, a, l: "vehicle 3 broke down"})()
    raw, reports = extract_reports(
        state,
        _fake_complete([{"event_type": "vehicle_breakdown",
                         "target_hint": "xe 3", "severity": "high"}]),
        audio=b"\x00\x01", transcriber=transcriber, lang="en-US")
    assert raw == "vehicle 3 broke down"
    assert reports[0].event_type == EventType.VEHICLE_BREAKDOWN
    assert reports[0].target == "V003"


def test_unresolved_target_dropped():
    state = build_sample_state()
    _, reports = extract_reports(
        state,
        _fake_complete([{"event_type": "vehicle_breakdown",
                         "target_hint": "does not exist", "severity": "low"}]),
        text="noise")
    assert reports == []
