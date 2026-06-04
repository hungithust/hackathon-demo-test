from fleet.contracts.interfaces import (
    Simulator, Detector, RouteOptimizer, Forecaster, DecisionEngine, Dispatcher,
)
from fleet.factory import Components, build_components
from fleet.routing.cpu_solver import CpuSolver
from fleet.agent.rule_based import RuleBasedEngine
from config.settings import load_settings


def test_build_components_returns_conforming_impls():
    c = build_components(load_settings())
    assert isinstance(c, Components)
    assert isinstance(c.simulator, Simulator)
    assert isinstance(c.detector, Detector)
    assert isinstance(c.optimizer, RouteOptimizer)
    assert isinstance(c.forecaster, Forecaster)
    assert isinstance(c.decision_engine, DecisionEngine)
    assert isinstance(c.dispatcher, Dispatcher)


def test_cpu_and_rule_are_the_defaults():
    c = build_components(load_settings(env={}))
    assert isinstance(c.optimizer, CpuSolver)
    assert isinstance(c.decision_engine, RuleBasedEngine)
