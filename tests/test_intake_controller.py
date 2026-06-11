import pytest

from fleet.intake.report import IntakeReport, IntakeResult
from fleet.intake.controller import IntakeController
from fleet.intake.asr import NullTranscriber
from fleet.ui.controller import SimulationController
from fleet.contracts.state import EventType, EventSeverity, EdgeStatus


def test_intake_report_defaults():
    r = IntakeReport(event_type=EventType.INVENTORY_SHORTAGE, target="C001",
                     severity=EventSeverity.HIGH, raw_text="kho C001 het hang")
    assert r.confidence == 1.0 and r.edge_status is None


def test_intake_result_holds_reports():
    res = IntakeResult(raw_text="x", reports=[], injected_event_ids=[], decisions=[])
    assert res.reports == [] and res.injected_event_ids == []


def _fake_complete(reports):
    return lambda system, user: {"reports": reports}


def test_text_report_injects_node_event_and_decides():
    sim = SimulationController()
    ic = IntakeController(sim, complete=_fake_complete([
        {"event_type": "inventory_shortage", "target_hint": "C001",
         "severity": "high"}]))
    result = ic.report(text="kho C001 het hang")
    assert len(result.injected_event_ids) == 1
    evt_id = result.injected_event_ids[0]
    # event landed in the world and the pipeline produced a decision for it
    assert any(e.id == evt_id for e in sim.state.events)
    assert any(d.event_id == evt_id for d in sim.state.decisions)


def test_edge_report_uses_disrupt_edge():
    sim = SimulationController()
    ic = IntakeController(sim, complete=_fake_complete([
        {"event_type": "flooded_area", "target_hint": "duong vao C001",
         "severity": "high", "edge_status": "flooded", "flood_level": 0.6}]))
    ic.report(text="duong vao C001 ngap")
    edge = sim.state.road_graph.get_edge("DEPOT->C001#2")
    assert edge.status == EdgeStatus.FLOODED and edge.flood_level == 0.6


def test_audio_path_transcribes_then_injects():
    sim = SimulationController()
    ic = IntakeController(
        sim,
        complete=_fake_complete([
            {"event_type": "vehicle_breakdown", "target_hint": "xe 3",
             "severity": "high"}]),
        transcriber=type("T", (), {"transcribe": lambda self, a, l: "xe 3 hong"})())
    result = ic.report(audio=b"\x00\x01")
    assert result.raw_text == "xe 3 hong"
    assert len(result.injected_event_ids) == 1


def test_bad_json_returns_empty_result_no_crash():
    sim = SimulationController()
    ic = IntakeController(sim, complete=lambda s, u: {"reports": [
        {"event_type": "not_a_type", "target_hint": "C001", "severity": "low"}]})
    result = ic.report(text="loi")
    assert result.injected_event_ids == [] and result.reports == []
