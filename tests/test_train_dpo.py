import json


def test_format_dpo_example_builds_prompt_chosen_rejected():
    from scripts.train_dpo import format_dpo_example
    rec = {"system": "S", "user": "U",
           "chosen": {"action": "reprioritize", "reasoning": "best", "added_delay_min": 3.0},
           "rejected": {"action": "cancel", "reasoning": "worse", "added_delay_min": 0.0}}
    out = format_dpo_example(rec)
    assert out["prompt"] == [{"role": "system", "content": "S"},
                             {"role": "user", "content": "U"}]
    assert out["chosen"][0]["role"] == "assistant"
    assert json.loads(out["chosen"][0]["content"]) == rec["chosen"]
    assert json.loads(out["rejected"][0]["content"]) == rec["rejected"]


def test_parse_args_defaults():
    from scripts.train_dpo import parse_args
    args = parse_args(["--prefs", "data/sb/prefs.jsonl"])
    assert args.prefs == "data/sb/prefs.jsonl"
    assert args.adapter == "/raid/team/adapters/sovereign-brain"
    assert args.epochs == 1 and args.beta == 0.1
