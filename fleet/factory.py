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
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.cuopt_adapter import CuOptAdapter
from fleet.forecast.ewma import EwmaForecaster
from fleet.agent.rule_based import RuleBasedEngine
from fleet.agent.claude_agent import ClaudeAgent
from fleet.dispatch.dispatcher import Dispatcher as DispatcherImpl


@dataclass
class Components:
    simulator: Simulator
    detector: Detector
    optimizer: RouteOptimizer
    forecaster: Forecaster
    decision_engine: DecisionEngine
    dispatcher: Dispatcher


def build_components(settings) -> Components:
    # Routing engine. cuOpt (GPU) when requested AND an endpoint is configured;
    # otherwise fall back to the CPU OR-Tools solver so the system always runs.
    if settings.routing_engine == "cuopt" and getattr(
            settings, "cuopt_endpoint", ""):
        optimizer: RouteOptimizer = CuOptAdapter(settings)
    else:
        optimizer = CpuSolver(settings)

    # Decision engine. Claude (LLM) when requested AND an API key is configured;
    # otherwise fall back to the rule-based engine so the system always runs.
    if settings.decision_engine == "claude" and getattr(
            settings, "anthropic_api_key", ""):
        decision_engine: DecisionEngine = ClaudeAgent(settings)
    else:
        decision_engine = RuleBasedEngine()

    # Detector: statistical z-score anomaly detector when requested, else the
    # rule-based threshold detector (default).
    if settings.detector_engine == "zscore":
        detector: Detector = ZScoreDetector(settings)
    else:
        detector = RuleDetector(settings)

    return Components(
        simulator=WorldSimulator(settings),
        detector=detector,
        optimizer=optimizer,
        forecaster=EwmaForecaster(settings),   # prophet not yet implemented (M6)
        decision_engine=decision_engine,
        dispatcher=DispatcherImpl(),
    )
