from fleet.contracts.interfaces import Detector
from fleet.detection.rules import RuleDetector
from fleet.scenarios import build_sample_state


def test_conforms_to_protocol():
    assert isinstance(RuleDetector(), Detector)


def test_detect_returns_empty_list_for_now():
    # M6 adds threshold rules; M1 stub finds nothing on its own.
    assert RuleDetector().detect(build_sample_state()) == []
