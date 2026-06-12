"""UI metadata for Settings: which fields to expose, how to render them, and how
to re-apply edited values. Single source of truth for the settings panel."""

import os
from dataclasses import dataclass, fields
from typing import List, Mapping, Optional, Tuple

from config.settings import Settings, load_settings


@dataclass(frozen=True)
class FieldSpec:
    key: str               # ENV-var name, e.g. "ROUTING_ENGINE"
    field: str             # dataclass attr, e.g. "routing_engine"
    label: str
    type: str              # "select" | "number" | "bool" | "text"
    group: str
    advanced: bool = False
    choices: Tuple[str, ...] = ()
    step: str = "any"      # number inputs only
    help: str = ""


CORE_SPECS: List[FieldSpec] = [
    FieldSpec("ROUTING_ENGINE", "routing_engine", "Routing engine", "select",
              "Engines", choices=("cpu", "cuopt"),
              help="cuopt needs CUOPT_ENDPOINT; otherwise falls back to cpu."),
    FieldSpec("DECISION_ENGINE", "decision_engine", "Decision engine", "select",
              "Engines", choices=("rule", "scoring", "claude", "nim"),
              help="claude needs ANTHROPIC_API_KEY; nim needs NIM_ENDPOINT; else rule."),
    FieldSpec("DETECTOR_ENGINE", "detector_engine", "Detector engine", "select",
              "Engines", choices=("rule", "zscore", "residual", "cusum", "layered")),
    FieldSpec("FORECASTER_ENGINE", "forecaster_engine", "Forecaster", "select",
              "Engines", choices=("ewma", "holt")),
    FieldSpec("WORLD", "world", "World", "select", "World & Time",
              choices=("sample", "real", "multidepot"),
              help="sample = 1 depot/10 veh; multidepot = 5 depots/50 veh/50 stops; "
                   "real needs data/hcm_drive.graphml + osmnx."),
    FieldSpec("SEED", "seed", "Random seed", "number", "World & Time", step="1"),
    FieldSpec("TICK_MINUTES", "tick_minutes", "Minutes per tick", "number",
              "World & Time", step="1"),
    FieldSpec("AUTO_APPROVE_DELAY_THRESHOLD_MIN", "auto_approve_delay_threshold_min",
              "Auto-approve delay (min)", "number", "Thresholds",
              help="Reroute/reschedule under this added delay auto-apply."),
    FieldSpec("SLA_CRITICAL_THRESHOLD_MIN", "sla_critical_threshold_min",
              "SLA critical (min)", "number", "Thresholds"),
    FieldSpec("ENABLE_WEATHER", "enable_weather", "Weather + flooding", "bool", "Toggles"),
    FieldSpec("ENABLE_TRAVEL_TIME", "enable_travel_time", "Replay travel time", "bool", "Toggles"),
    FieldSpec("ENABLE_PROACTIVE", "enable_proactive", "Proactive decisions", "bool", "Toggles"),
]

_CORE_FIELDS = {s.field for s in CORE_SPECS}


def _infer_type(value) -> str:
    if isinstance(value, bool):        # bool before int (bool is a subclass)
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


def build_specs(settings_cls=Settings) -> List[FieldSpec]:
    """CORE_SPECS + an auto Advanced spec for every other Settings field."""
    specs = list(CORE_SPECS)
    defaults = settings_cls()
    for f in fields(settings_cls):
        if f.name in _CORE_FIELDS:
            continue
        val = getattr(defaults, f.name)
        is_int = isinstance(val, int) and not isinstance(val, bool)
        specs.append(FieldSpec(
            key=f.name.upper(), field=f.name,
            label=f.name.replace("_", " ").capitalize(),
            type=_infer_type(val), group="Advanced", advanced=True,
            step=("1" if is_int else "any"),
        ))
    return specs


def current_values(settings) -> dict:
    """Current value per spec, keyed by ENV-var name. JSON-safe."""
    return {s.key: getattr(settings, s.field) for s in build_specs()}


def _to_env_str(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def apply(overrides: Mapping[str, object],
          base_env: Optional[Mapping[str, str]] = None) -> Settings:
    """Merge {ENV_VAR: value} over base_env, then rebuild Settings via
    load_settings. Raises ValueError if a value cannot be parsed (bad int/float)."""
    base = dict(os.environ if base_env is None else base_env)
    for k, v in overrides.items():
        base[k] = _to_env_str(v)
    return load_settings(base)
