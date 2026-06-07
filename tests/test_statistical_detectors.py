from fleet.contracts.state import EventSeverity
from fleet.detection.severity import severity_from_z
from fleet.contracts.interfaces import Detector
from fleet.detection.forecast_residual import ForecastResidualDetector
from fleet.forecast.holt_winters import HoltWintersForecaster
from fleet.contracts.state import EventType
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def _set_orders(state, cid, total):
    state.customers[cid].orders = {"SKU001": int(total)}


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


def test_residual_detector_conforms_to_protocol():
    s = load_settings(env={"SEASON_LENGTH": "3"})
    d = ForecastResidualDetector(s, HoltWintersForecaster(s))
    assert isinstance(d, Detector)


def test_residual_flags_demand_above_band():
    s = load_settings(env={"SEASON_LENGTH": "3", "DETECTOR_MIN_HISTORY": "6"})
    d = ForecastResidualDetector(s, HoltWintersForecaster(s))
    state = build_sample_state()
    # feed a stable history for C001, then a big spike
    for _ in range(12):
        _set_orders(state, "C001", 10)
        d.detect(state)
    _set_orders(state, "C001", 80)                  # large surge
    events = d.detect(state)
    surges = [e for e in events if e.event_type == EventType.DEMAND_SURGE
              and e.target == "C001"]
    assert len(surges) == 1
    assert surges[0].id == "DET_RESID_C001"


def test_residual_quiet_when_demand_in_band():
    s = load_settings(env={"SEASON_LENGTH": "3", "DETECTOR_MIN_HISTORY": "6"})
    d = ForecastResidualDetector(s, HoltWintersForecaster(s))
    state = build_sample_state()
    events = []
    for _ in range(14):
        _set_orders(state, "C001", 10)              # perfectly stable
        events = d.detect(state)
    c001 = [e for e in events if e.target == "C001"]
    assert c001 == []                               # no false positive on stable demand


def test_cusum_conforms_to_protocol():
    from fleet.detection.cusum import CusumDetector
    assert isinstance(CusumDetector(load_settings()), Detector)


def test_cusum_flags_sustained_upward_drift():
    from fleet.detection.cusum import CusumDetector
    s = load_settings(env={"DETECTOR_MIN_HISTORY": "6", "CUSUM_THRESHOLD": "4.0"})
    d = CusumDetector(s)
    state = build_sample_state()
    # establish a stable baseline
    for _ in range(10):
        _set_orders(state, "C001", 10)
        d.detect(state)
    # then a sustained higher level (regime shift) -> CUSUM accumulates -> alarm
    fired = False
    for _ in range(10):
        _set_orders(state, "C001", 16)
        events = d.detect(state)
        if any(e.id == "DET_CUSUM_C001" for e in events):
            fired = True
            break
    assert fired


def test_cusum_quiet_on_stable_demand():
    from fleet.detection.cusum import CusumDetector
    s = load_settings(env={"DETECTOR_MIN_HISTORY": "6"})
    d = CusumDetector(s)
    state = build_sample_state()
    fired = False
    for _ in range(30):
        _set_orders(state, "C001", 10)
        if any(e.id == "DET_CUSUM_C001" for e in d.detect(state)):
            fired = True
    assert not fired


def test_composite_concatenates_member_events():
    from fleet.detection.composite import CompositeDetector
    from fleet.detection.rules import RuleDetector
    from fleet.detection.cusum import CusumDetector
    s = load_settings(env={"DETECTOR_MIN_HISTORY": "6", "SEASON_LENGTH": "3"})
    comp = CompositeDetector([
        RuleDetector(s),
        CusumDetector(s),
    ])
    state = build_sample_state()
    # RuleDetector fires on the sample world's permanently FLOODED #2 edge each call
    events = comp.detect(state)
    assert any(e.id.startswith("DET_FLOOD_") for e in events)
    assert isinstance(events, list)
