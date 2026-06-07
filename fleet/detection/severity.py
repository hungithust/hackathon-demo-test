"""Map a standardized anomaly magnitude (z = sigmas beyond expectation) to an
EventSeverity band (M-C §5.3). Shared by the forecast-residual and CUSUM
detectors so severity is principled, not hard-coded."""

from fleet.contracts.state import EventSeverity


def severity_from_z(z: float) -> EventSeverity:
    if z >= 4.0:
        return EventSeverity.CRITICAL
    if z >= 3.0:
        return EventSeverity.HIGH
    if z >= 2.0:
        return EventSeverity.MEDIUM
    return EventSeverity.LOW
