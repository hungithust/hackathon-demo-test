from fleet.contracts.state import EventSeverity
from fleet.detection.severity import severity_from_z


def test_severity_bands():
    assert severity_from_z(0.5) == EventSeverity.LOW
    assert severity_from_z(2.0) == EventSeverity.MEDIUM
    assert severity_from_z(3.0) == EventSeverity.HIGH
    assert severity_from_z(4.5) == EventSeverity.CRITICAL


def test_severity_monotonic():
    order = [EventSeverity.LOW, EventSeverity.MEDIUM, EventSeverity.HIGH,
             EventSeverity.CRITICAL]
    zs = [0.0, 2.0, 3.0, 4.0]
    sevs = [severity_from_z(z) for z in zs]
    assert [order.index(s) for s in sevs] == sorted(order.index(s) for s in sevs)
