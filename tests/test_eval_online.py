from config.settings import load_settings


def test_engine_metrics_keys_and_determinism():
    from fleet.agent.rule_based import RuleBasedEngine
    from fleet.eval.online import engine_metrics

    settings = load_settings({})
    m1 = engine_metrics(settings, RuleBasedEngine(), n_ticks=8)
    assert set(m1) == {"delivered", "on_time", "on_time_pct",
                       "total_delay_min", "total_cost"}
    assert 0.0 <= m1["on_time_pct"] <= 1.0
    assert m1["total_delay_min"] >= 0.0
    # determinism: a fresh rule engine over the same seed -> identical metrics
    m2 = engine_metrics(settings, RuleBasedEngine(), n_ticks=8)
    assert m1 == m2


def test_decide_latency_is_nonnegative():
    from fleet.agent.scoring_engine import ScoringEngine
    from fleet.contracts.state import Event, EventType, EventSeverity
    from fleet.scenarios import build_sample_state
    from fleet.eval.online import decide_latency_seconds

    settings = load_settings({})
    state = build_sample_state()
    evt = Event(id="E1", event_type=EventType.DEMAND_SURGE, target="C001",
                severity=EventSeverity.MEDIUM, started_at=state.clock)
    secs = decide_latency_seconds(ScoringEngine(settings), state, [evt])
    assert secs >= 0.0
