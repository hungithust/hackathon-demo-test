from fleet.contracts.interfaces import (
    Simulator, Detector, RouteOptimizer, Forecaster, DecisionEngine, Dispatcher,
)
from fleet.factory import Components, build_components
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.cuopt_adapter import CuOptAdapter
from fleet.agent.rule_based import RuleBasedEngine
from fleet.agent.claude_agent import ClaudeAgent
from fleet.detection.rules import RuleDetector
from fleet.detection.zscore import ZScoreDetector
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


def test_claude_engine_with_key_selects_claude_agent():
    s = load_settings(env={"DECISION_ENGINE": "claude",
                           "ANTHROPIC_API_KEY": "sk-test"})
    comps = build_components(s)
    assert isinstance(comps.decision_engine, ClaudeAgent)


def test_claude_engine_without_key_falls_back_to_rule():
    s = load_settings(env={"DECISION_ENGINE": "claude",
                           "ANTHROPIC_API_KEY": ""})
    comps = build_components(s)
    assert isinstance(comps.decision_engine, RuleBasedEngine)


def test_default_detector_is_rule():
    comps = build_components(load_settings(env={}))
    assert isinstance(comps.detector, RuleDetector)


def test_zscore_detector_selected_by_setting():
    comps = build_components(load_settings(env={"DETECTOR_ENGINE": "zscore"}))
    assert isinstance(comps.detector, ZScoreDetector)


def test_factory_selects_holt_winters_when_requested():
    from fleet.forecast.holt_winters import HoltWintersForecaster
    c = build_components(load_settings(env={"FORECASTER_ENGINE": "holt"}))
    assert isinstance(c.forecaster, HoltWintersForecaster)


def test_factory_defaults_to_ewma_forecaster():
    from fleet.forecast.ewma import EwmaForecaster
    c = build_components(load_settings(env={}))
    assert isinstance(c.forecaster, EwmaForecaster)


def test_factory_selects_layered_detector():
    from fleet.detection.composite import CompositeDetector
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={"DETECTOR_ENGINE": "layered"}))
    assert isinstance(c.detector, CompositeDetector)


def test_factory_defaults_to_rule_detector():
    from fleet.detection.rules import RuleDetector
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={}))
    assert isinstance(c.detector, RuleDetector)


def test_factory_selects_scoring_engine():
    from fleet.agent.scoring_engine import ScoringEngine
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={"DECISION_ENGINE": "scoring"}))
    assert isinstance(c.decision_engine, ScoringEngine)


def test_factory_defaults_to_rule_engine():
    from fleet.agent.rule_based import RuleBasedEngine
    from fleet.factory import build_components
    from config.settings import load_settings
    c = build_components(load_settings(env={}))
    assert isinstance(c.decision_engine, RuleBasedEngine)


def test_factory_selects_nim_agent_when_endpoint_set():
    from fleet.factory import build_components
    from fleet.agent.nim_agent import NimAgent
    from config.settings import load_settings
    s = load_settings({"DECISION_ENGINE": "nim",
                       "NIM_ENDPOINT": "http://localhost:8000/v1"})
    assert isinstance(build_components(s).decision_engine, NimAgent)


def test_factory_nim_without_endpoint_falls_back_to_rule():
    from fleet.factory import build_components
    from fleet.agent.rule_based import RuleBasedEngine
    from config.settings import load_settings
    s = load_settings({"DECISION_ENGINE": "nim"})   # engine requested, no endpoint
    assert isinstance(build_components(s).decision_engine, RuleBasedEngine)


def test_build_transcriber_defaults_to_null():
    from config.settings import load_settings
    from fleet.factory import build_transcriber
    from fleet.intake.asr import NullTranscriber
    t = build_transcriber(load_settings({}))
    assert isinstance(t, NullTranscriber)


def test_build_transcriber_selects_whisper():
    from config.settings import load_settings
    from fleet.factory import build_transcriber
    from fleet.intake.asr import WhisperTranscriber
    t = build_transcriber(load_settings({"ASR_ENGINE": "whisper"}))
    assert isinstance(t, WhisperTranscriber)
