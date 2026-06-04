import os

from config.settings import Settings, load_settings


def test_defaults():
    s = load_settings(env={})
    assert s.routing_engine == "cpu"
    assert s.decision_engine == "rule"
    assert s.forecaster_engine == "ewma"
    assert s.detector_engine == "rule"
    assert s.seed == 42
    assert s.tick_minutes == 5
    assert s.auto_approve_delay_threshold_min == 15.0
    assert s.sla_critical_threshold_min == 30.0


def test_env_overrides():
    s = load_settings(env={"ROUTING_ENGINE": "cuopt",
                           "DECISION_ENGINE": "claude",
                           "SEED": "7",
                           "TICK_MINUTES": "10"})
    assert s.routing_engine == "cuopt"
    assert s.decision_engine == "claude"
    assert s.seed == 7
    assert s.tick_minutes == 10


def test_is_frozen():
    s = Settings()
    try:
        s.seed = 1  # type: ignore[misc]
        raise AssertionError("Settings should be immutable")
    except Exception:
        pass
