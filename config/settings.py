"""Central configuration. Engine choices select which interface impl the
factory returns, so changing CPU<->cuOpt or rule<->claude is config-only."""

import os
from dataclasses import dataclass
from typing import Mapping, Optional


@dataclass(frozen=True)
class Settings:
    routing_engine: str = "cpu"        # cpu | cuopt
    decision_engine: str = "rule"      # rule | claude
    detector_engine: str = "rule"      # rule | zscore
    forecaster_engine: str = "ewma"    # ewma | prophet
    seed: int = 42
    tick_minutes: int = 5
    anthropic_api_key: str = ""
    cuopt_endpoint: str = ""
    auto_approve_delay_threshold_min: float = 15.0   # spec §6.6
    sla_critical_threshold_min: float = 30.0         # spec §6.2
    demand_noise: float = 0.3                        # M2: demand multiplicative noise (±)
    restock_interval_min: int = 240                  # M2: depot restock cadence (sim minutes)
    solver_time_limit_sec: int = 0                   # M3: >0 enables OR-Tools GLS (else deterministic)
    ewma_alpha: float = 0.3                # M6: EWMA smoothing factor (0,1]
    zscore_threshold: float = 2.0          # M6: demand-anomaly z-score cutoff
    traffic_alert_factor: float = 3.0      # M6: traffic_factor at/above this -> TRAFFIC event
    demand_trend_per_day: float = 0.05    # M-A: slow multiplicative growth per sim-day
    demand_weekend_factor: float = 0.7    # M-A: Sat/Sun demand multiplier
    demand_ar_rho: float = 0.6            # M-A: AR(1) autocorrelation of demand noise
    demand_ar_sigma: float = 0.3          # M-A: AR(1) lognormal noise scale
    regime_prob: float = 0.01             # M-A: per-customer per-tick chance to enter a promo regime
    regime_factor: float = 2.0            # M-A: demand multiplier while in a regime
    regime_duration_min: int = 180        # M-A: regime length (sim minutes)
    enable_weather: bool = False          # M-A2: gate traffic+weather edge mutation
    traffic_peak_factor: float = 1.8      # M-A2: rush-hour traffic_factor at peak (< traffic_alert_factor)
    weather_rho: float = 0.8              # M-A2: AR(1) autocorrelation of the rain process
    weather_flood_threshold: float = 0.7  # M-A2: rain level at/above which flood-prone edges flood
    weather_flood_level: float = 0.5      # M-A2: flood depth applied while flooded (m)


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Build Settings from environment variables (defaults to os.environ)."""
    e = os.environ if env is None else env
    return Settings(
        routing_engine=e.get("ROUTING_ENGINE", "cpu"),
        decision_engine=e.get("DECISION_ENGINE", "rule"),
        detector_engine=e.get("DETECTOR_ENGINE", "rule"),
        forecaster_engine=e.get("FORECASTER_ENGINE", "ewma"),
        seed=int(e.get("SEED", "42")),
        tick_minutes=int(e.get("TICK_MINUTES", "5")),
        anthropic_api_key=e.get("ANTHROPIC_API_KEY", ""),
        cuopt_endpoint=e.get("CUOPT_ENDPOINT", ""),
        auto_approve_delay_threshold_min=float(
            e.get("AUTO_APPROVE_DELAY_THRESHOLD_MIN", "15")),
        sla_critical_threshold_min=float(
            e.get("SLA_CRITICAL_THRESHOLD_MIN", "30")),
        demand_noise=float(e.get("DEMAND_NOISE", "0.3")),
        restock_interval_min=int(e.get("RESTOCK_INTERVAL_MIN", "240")),
        solver_time_limit_sec=int(e.get("SOLVER_TIME_LIMIT_SEC", "0")),
        ewma_alpha=float(e.get("EWMA_ALPHA", "0.3")),
        zscore_threshold=float(e.get("ZSCORE_THRESHOLD", "2.0")),
        traffic_alert_factor=float(e.get("TRAFFIC_ALERT_FACTOR", "3")),
        demand_trend_per_day=float(e.get("DEMAND_TREND_PER_DAY", "0.05")),
        demand_weekend_factor=float(e.get("DEMAND_WEEKEND_FACTOR", "0.7")),
        demand_ar_rho=float(e.get("DEMAND_AR_RHO", "0.6")),
        demand_ar_sigma=float(e.get("DEMAND_AR_SIGMA", "0.3")),
        regime_prob=float(e.get("REGIME_PROB", "0.01")),
        regime_factor=float(e.get("REGIME_FACTOR", "2.0")),
        regime_duration_min=int(e.get("REGIME_DURATION_MIN", "180")),
        enable_weather=e.get("ENABLE_WEATHER", "0") in ("1", "true", "True"),
        traffic_peak_factor=float(e.get("TRAFFIC_PEAK_FACTOR", "1.8")),
        weather_rho=float(e.get("WEATHER_RHO", "0.8")),
        weather_flood_threshold=float(e.get("WEATHER_FLOOD_THRESHOLD", "0.7")),
        weather_flood_level=float(e.get("WEATHER_FLOOD_LEVEL", "0.5")),
    )
