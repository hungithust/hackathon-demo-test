"""Evaluation harness (Sovereign Brain v2, M-D). Offline: prediction-vs-oracle
agreement / JSON-validity / confusion on a held-out JSONL. Online: each engine
through the loop on on-time % / cost / delay, plus decision latency.

  python -m scripts.eval_brain --test data/sovereign-brain/test.jsonl
  python -m scripts.eval_brain --test ... --nim-endpoint http://localhost:8000/v1
"""

import argparse
import json

from config.settings import load_settings
from fleet.agent.rule_based import RuleBasedEngine, _ACTION_BY_EVENT
from fleet.agent.scoring_engine import ScoringEngine
from fleet.contracts.state import EventType, DecisionAction
from fleet.eval.offline import predict_records, summarize_offline
from fleet.eval.online import engine_metrics


def _load_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def rule_predictor():
    """A $0 baseline predictor: map the event type to the rule-based action."""
    def complete(system, user):
        first = user.split("\n", 1)[0]
        value = first.split("Event type:", 1)[1].strip() if "Event type:" in first else ""
        try:
            action = _ACTION_BY_EVENT.get(EventType(value), DecisionAction.REROUTE)
        except ValueError:
            action = DecisionAction.REROUTE
        return {"action": action.value, "reasoning": "rule", "added_delay_min": 5.0}
    return complete


def run_offline(test_path, predict_complete):
    rows = predict_records(_load_jsonl(test_path), predict_complete)
    return summarize_offline(rows)


def run_online(settings, n_ticks, nim_endpoint=""):
    engines = {"rule": RuleBasedEngine(), "scoring": ScoringEngine(settings)}
    if nim_endpoint:
        from fleet.agent.nim_agent import NimAgent
        from dataclasses import replace
        engines["nim"] = NimAgent(replace(settings, nim_endpoint=nim_endpoint))
    return {name: engine_metrics(settings, eng, n_ticks)
            for name, eng in engines.items()}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--test", help="held-out test.jsonl for the offline eval")
    p.add_argument("--ticks", type=int, default=24)
    p.add_argument("--nim-endpoint", dest="nim_endpoint", default="",
                   help="if set, also eval NimAgent online and offline")
    args = p.parse_args()
    settings = load_settings()

    report = {"online": run_online(settings, args.ticks, args.nim_endpoint)}
    if args.test:
        if args.nim_endpoint:
            from fleet.agent.nim_agent import NimAgent
            from dataclasses import replace
            agent = NimAgent(replace(settings, nim_endpoint=args.nim_endpoint))
            predict = agent._get_complete()
            report["offline_nim"] = run_offline(args.test, predict)
        report["offline_rule_baseline"] = run_offline(args.test, rule_predictor())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
