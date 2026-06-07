from datetime import timedelta

from fleet.contracts.state import EdgeStatus
from fleet.simulator.engine import WorldSimulator, _traffic_factor_for_hour
from fleet.scenarios import build_sample_state
from config.settings import load_settings


def test_traffic_peaks_at_rush_hours_and_stays_below_alert():
    peak = 1.8
    alert = 3.0
    assert _traffic_factor_for_hour(8, peak) == peak        # morning rush
    assert _traffic_factor_for_hour(18, peak) == peak       # evening rush
    assert _traffic_factor_for_hour(13, peak) < peak        # midday lighter
    assert _traffic_factor_for_hour(3, peak) == 1.0         # night = free flow
    assert _traffic_factor_for_hour(8, peak) < alert        # never a false TRAFFIC alert
