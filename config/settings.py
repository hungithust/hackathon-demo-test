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
    )
