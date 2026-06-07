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
    assert s.demand_noise == 0.3
    assert s.restock_interval_min == 240
    assert s.solver_time_limit_sec == 0
    assert s.ewma_alpha == 0.3
    assert s.zscore_threshold == 2.0
    assert s.traffic_alert_factor == 3.0


def test_m6_setting_env_overrides():
    s = load_settings(env={"EWMA_ALPHA": "0.5",
                           "ZSCORE_THRESHOLD": "2.5",
                           "TRAFFIC_ALERT_FACTOR": "4"})
    assert s.ewma_alpha == 0.5
    assert s.zscore_threshold == 2.5
    assert s.traffic_alert_factor == 4.0


def test_solver_time_limit_env_override():
    s = load_settings(env={"SOLVER_TIME_LIMIT_SEC": "5"})
    assert s.solver_time_limit_sec == 5


def test_env_overrides():
    s = load_settings(env={"ROUTING_ENGINE": "cuopt",
                           "DECISION_ENGINE": "claude",
                           "SEED": "7",
                           "TICK_MINUTES": "10"})
    assert s.routing_engine == "cuopt"
    assert s.decision_engine == "claude"
    assert s.seed == 7
    assert s.tick_minutes == 10


def test_m2_env_overrides():
    s = load_settings(env={"DEMAND_NOISE": "0.5", "RESTOCK_INTERVAL_MIN": "60"})
    assert s.demand_noise == 0.5
    assert s.restock_interval_min == 60


def test_latent_process_defaults():
    s = load_settings(env={})
    assert s.demand_trend_per_day == 0.05
    assert s.demand_weekend_factor == 0.7
    assert s.demand_ar_rho == 0.6
    assert s.demand_ar_sigma == 0.3
    assert s.regime_prob == 0.01
    assert s.regime_factor == 2.0
    assert s.regime_duration_min == 180


def test_latent_process_env_override():
    s = load_settings(env={"DEMAND_AR_RHO": "0.9", "REGIME_FACTOR": "3.5"})
    assert s.demand_ar_rho == 0.9
    assert s.regime_factor == 3.5


def test_weather_defaults():
    s = load_settings(env={})
    assert s.enable_weather is False
    assert s.traffic_peak_factor == 1.8
    assert s.weather_rho == 0.8
    assert s.weather_flood_threshold == 0.7
    assert s.weather_flood_level == 0.5


def test_weather_env_override():
    s = load_settings(env={"ENABLE_WEATHER": "1", "TRAFFIC_PEAK_FACTOR": "2.2"})
    assert s.enable_weather is True
    assert s.traffic_peak_factor == 2.2


def test_holt_winters_defaults():
    s = load_settings(env={})
    assert s.hw_alpha == 0.3
    assert s.hw_beta == 0.1
    assert s.hw_gamma == 0.1
    assert s.season_length == 24
    assert s.pi_z == 1.96


def test_holt_winters_env_override():
    s = load_settings(env={"FORECASTER_ENGINE": "holt", "SEASON_LENGTH": "12"})
    assert s.forecaster_engine == "holt"
    assert s.season_length == 12


def test_is_frozen():
    s = Settings()
    try:
        s.seed = 1  # type: ignore[misc]
        raise AssertionError("Settings should be immutable")
    except Exception:
        pass
