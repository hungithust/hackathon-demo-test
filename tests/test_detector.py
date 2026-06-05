from fleet.contracts.interfaces import Detector
from fleet.detection.rules import RuleDetector
from fleet.scenarios import build_sample_state


def test_conforms_to_protocol():
    assert isinstance(RuleDetector(), Detector)


def test_detect_finds_sample_world_flood():
    # M6 RuleDetector applies real threshold rules: the sample world's parallel
    # flooded DEPOT<->C001 links surface FLOODED_AREA events each tick.
    from fleet.contracts.state import EventType
    events = RuleDetector().detect(build_sample_state())
    assert any(e.event_type == EventType.FLOODED_AREA for e in events)
