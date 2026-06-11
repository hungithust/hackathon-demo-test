import json


def test_format_chat_example_builds_chat_with_json_assistant():
    from scripts.train_lora import format_chat_example
    rec = {"system": "S", "user": "U",
           "assistant": {"action": "reroute", "reasoning": "r", "added_delay_min": 3.0}}
    out = format_chat_example(rec)
    msgs = out["messages"]
    assert msgs[0] == {"role": "system", "content": "S"}
    assert msgs[1] == {"role": "user", "content": "U"}
    assert msgs[2]["role"] == "assistant"
    assert json.loads(msgs[2]["content"]) == rec["assistant"]   # strict decision JSON


def test_parse_args_defaults():
    from scripts.train_lora import parse_args
    args = parse_args(["--train", "data/sb/train.jsonl"])
    assert args.train == "data/sb/train.jsonl"
    assert args.base_model == "nvidia/Llama-3.1-Nemotron-Nano-8B-v1"
    assert args.epochs == 3 and args.lora_r == 16 and args.seed == 42
