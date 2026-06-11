"""Composition root: reads Settings and returns concrete impls behind the
interfaces. This is the ONLY place that knows about every impl, so swapping an
engine is a config change here, not in callers (loop, agent, ui)."""

from dataclasses import dataclass

from fleet.contracts.interfaces import (
    Simulator, Detector, RouteOptimizer, Forecaster, DecisionEngine, Dispatcher,
)
from fleet.simulator.engine import WorldSimulator
from fleet.detection.rules import RuleDetector
from fleet.detection.zscore import ZScoreDetector
from fleet.detection.forecast_residual import ForecastResidualDetector
from fleet.detection.cusum import CusumDetector
from fleet.detection.composite import CompositeDetector
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.cuopt_adapter import CuOptAdapter
from fleet.forecast.ewma import EwmaForecaster
from fleet.forecast.holt_winters import HoltWintersForecaster
from fleet.agent.rule_based import RuleBasedEngine
from fleet.agent.scoring_engine import ScoringEngine
from fleet.agent.claude_agent import ClaudeAgent
from fleet.agent.nim_agent import NimAgent
from fleet.dispatch.dispatcher import Dispatcher as DispatcherImpl
from fleet.intake.asr import NullTranscriber, WhisperTranscriber, RivaTranscriber


@dataclass
class Components:
    simulator: Simulator
    detector: Detector
    optimizer: RouteOptimizer
    forecaster: Forecaster
    decision_engine: DecisionEngine
    dispatcher: Dispatcher


class _WithCpuFallback:
    """Wraps a primary optimizer (e.g. CuOptAdapter) with automatic fallback to
    CpuSolver on any exception, so a cuOpt timeout / overload never 500s the API."""

    def __init__(self, primary: RouteOptimizer, fallback: RouteOptimizer):
        self.primary = primary
        self.fallback = fallback

    def solve(self, problem):
        try:
            return self.primary.solve(problem)
        except Exception as exc:
            print(f"[optimizer] primary solver failed ({exc}); falling back to CpuSolver")
            return self.fallback.solve(problem)


def build_components(settings) -> Components:
    # Routing engine. cuOpt (GPU) when requested AND an endpoint is configured;
    # otherwise fall back to the CPU OR-Tools solver so the system always runs.
    # cuOpt is always wrapped with _WithCpuFallback so any network/timeout error
    # auto-retries on CPU without surfacing a 500 to the UI.
    cpu = CpuSolver(settings)
    if settings.routing_engine == "cuopt" and getattr(
            settings, "cuopt_endpoint", ""):
        optimizer: RouteOptimizer = _WithCpuFallback(CuOptAdapter(settings), cpu)
    else:
        optimizer = cpu

    # Decision engine. NIM (self-hosted LLM) when requested AND an endpoint is
    # set; Claude (LLM) when requested AND an API key is configured; the scoring
    # policy when requested; otherwise the rule-based engine so the system always
    # runs.
    if settings.decision_engine == "nim" and getattr(settings, "nim_endpoint", ""):
        decision_engine: DecisionEngine = NimAgent(settings)
    elif settings.decision_engine == "claude" and getattr(
            settings, "anthropic_api_key", ""):
        decision_engine = ClaudeAgent(settings)
    elif settings.decision_engine == "scoring":
        decision_engine = ScoringEngine(settings)
    else:
        decision_engine = RuleBasedEngine()

    # Forecaster: Holt-Winters (level+trend+seasonality+intervals) when requested,
    # else the default EWMA. (prophet remains a future, unimplemented slot.)
    # Built before the detector so the residual detector can reuse it.
    if settings.forecaster_engine == "holt":
        forecaster: Forecaster = HoltWintersForecaster(settings)
    else:
        forecaster = EwmaForecaster(settings)

    # The forecast-residual detector needs an interval-producing forecaster, so
    # use the built one if it is Holt-Winters, else construct one regardless of
    # FORECASTER_ENGINE (EWMA gives no prediction band).
    interval_forecaster = (forecaster if isinstance(forecaster, HoltWintersForecaster)
                           else HoltWintersForecaster(settings))

    # Detector: statistical detectors (history-aware) when requested, the layered
    # composite (ground-truth RuleDetector + residual + CUSUM), else the default
    # rule-based threshold detector. zscore kept for back-compat.
    if settings.detector_engine == "zscore":
        detector: Detector = ZScoreDetector(settings)
    elif settings.detector_engine == "residual":
        detector = ForecastResidualDetector(settings, interval_forecaster)
    elif settings.detector_engine == "cusum":
        detector = CusumDetector(settings)
    elif settings.detector_engine == "layered":
        detector = CompositeDetector([
            RuleDetector(settings),
            ForecastResidualDetector(settings, interval_forecaster),
            CusumDetector(settings),
        ])
    else:
        detector = RuleDetector(settings)

    return Components(
        simulator=WorldSimulator(settings),
        detector=detector,
        optimizer=optimizer,
        forecaster=forecaster,
        decision_engine=decision_engine,
        dispatcher=DispatcherImpl(),
    )


def build_transcriber(settings):
    """Select the ASR impl. Defaults to NullTranscriber (text-only) so the
    feature is OFF unless ASR_ENGINE is set."""
    if settings.asr_engine == "whisper":
        return WhisperTranscriber(settings)
    if settings.asr_engine == "riva" and getattr(settings, "riva_endpoint", ""):
        return RivaTranscriber(settings)
    return NullTranscriber()
