"""Composition root: reads Settings and returns concrete impls behind the
interfaces. This is the ONLY place that knows about every impl, so swapping an
engine is a config change here, not in callers (loop, agent, ui)."""

from dataclasses import dataclass

from fleet.contracts.interfaces import (
    Simulator, Detector, RouteOptimizer, Forecaster, DecisionEngine, Dispatcher,
)
from fleet.simulator.engine import WorldSimulator
from fleet.detection.rules import RuleDetector
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.cuopt_adapter import CuOptAdapter
from fleet.forecast.ewma import EwmaForecaster
from fleet.agent.rule_based import RuleBasedEngine
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

    # Decision engine (Claude arrives in M5; rule-based is the default/fallback).
    if settings.decision_engine == "claude":
        decision_engine: DecisionEngine = RuleBasedEngine()  # TODO M5: ClaudeAgent
    else:
        decision_engine = RuleBasedEngine()

    return Components(
        simulator=WorldSimulator(settings),
        detector=RuleDetector(),
        optimizer=optimizer,
        forecaster=EwmaForecaster(),
        decision_engine=decision_engine,
        dispatcher=DispatcherImpl(),
    )
