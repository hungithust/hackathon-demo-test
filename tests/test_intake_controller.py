from fleet.intake.report import IntakeReport, IntakeResult
from fleet.contracts.state import EventType, EventSeverity, EdgeStatus


def test_intake_report_defaults():
    r = IntakeReport(event_type=EventType.INVENTORY_SHORTAGE, target="C001",
                     severity=EventSeverity.HIGH, raw_text="kho C001 het hang")
    assert r.confidence == 1.0
    assert r.edge_status is None
    assert r.flood_level == 0.0
    assert r.traffic_factor == 1.0


def test_intake_result_holds_reports():
    res = IntakeResult(raw_text="x", reports=[], injected_event_ids=[], decisions=[])
    assert res.reports == [] and res.injected_event_ids == []
