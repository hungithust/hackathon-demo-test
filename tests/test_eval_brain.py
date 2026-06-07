import json
from pathlib import Path

from config.settings import load_settings


def test_run_online_compares_rule_and_scoring():
    from scripts.eval_brain import run_online
    rep = run_online(load_settings({}), n_ticks=8)
    assert set(rep) >= {"rule", "scoring"}
    assert 0.0 <= rep["rule"]["on_time_pct"] <= 1.0
    assert "total_cost" in rep["scoring"]


def test_run_offline_over_jsonl_with_rule_predictor(tmp_path):
    from scripts.eval_brain import run_offline, rule_predictor
    from fleet.agent.dataset import build_record
    from fleet.contracts.state import Event, EventType, EventSeverity, DecisionAction
    from fleet.scenarios import build_sample_state

    state = build_sample_state()
    evt = Event(id="E1", event_type=EventType.TRAFFIC, target="e1",
                severity=EventSeverity.MEDIUM, started_at=state.clock)
    rec = build_record(state, evt, DecisionAction.REROUTE, 5.0, "x")
    path = tmp_path / "test.jsonl"
    path.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    summary = run_offline(str(path), rule_predictor())
    assert summary["n"] == 1
    assert 0.0 <= summary["agreement_pct"] <= 1.0
    # the rule predictor maps TRAFFIC -> reroute, which is the gold here
    assert summary["validity_pct"] == 1.0
