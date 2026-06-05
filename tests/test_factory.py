from fleet.contracts.interfaces import (
    Simulator, Detector, RouteOptimizer, Forecaster, DecisionEngine, Dispatcher,
)
from fleet.factory import Components, build_components
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.cuopt_adapter import CuOptAdapter
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


def test_cuopt_engine_with_endpoint_selects_cuopt_adapter():
    s = load_settings(env={"ROUTING_ENGINE": "cuopt",
                           "CUOPT_ENDPOINT": "localhost:5000"})
    comps = build_components(s)
    assert isinstance(comps.optimizer, CuOptAdapter)


def test_cuopt_engine_without_endpoint_falls_back_to_cpu():
    s = load_settings(env={"ROUTING_ENGINE": "cuopt", "CUOPT_ENDPOINT": ""})
    comps = build_components(s)
    assert isinstance(comps.optimizer, CpuSolver)
