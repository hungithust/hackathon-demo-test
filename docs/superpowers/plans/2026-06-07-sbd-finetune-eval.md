# Sovereign Brain v2 — M-D Fine-tune + Eval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LoRA-fine-tune the NIM base model on the oracle-verified dataset, and build an evaluation harness that compares the brain against Claude / rule / scoring on agreement, JSON-validity, on-time %, cost/delay, and decision latency.

**Architecture:** The **evaluation** logic lives in a new pure `fleet/eval/` package — `offline.py` (prediction vs the oracle-verified gold label: agreement %, JSON-validity, per-event confusion) and `online.py` (run an engine through the real loop and read on-time % / cost / delay / latency). Both are CPU-only and testable; the model transport is injected. The **training** driver `scripts/train_lora.py` keeps all heavy GPU imports (`torch`/`trl`/`peft`) inside `main()` so the one pure, testable piece — `format_chat_example` (JSONL row → chat-template example) — imports without a GPU. `scripts/eval_brain.py` is a thin CLI that runs the offline + online comparison and prints the report. Depends on M-B (the dataset) and M-A (`realized_cost`); reuses M-C's `NimAgent` transport for the real model.

**Tech Stack:** Python, HF Transformers + TRL `SFTTrainer` + PEFT LoRA (GPU, run on the H200s), existing simulator/loop/oracle/agents, pytest.

---

### Task 1: Offline eval — prediction vs oracle gold

**Files:**
- Create: `fleet/eval/__init__.py` (empty)
- Create: `fleet/eval/offline.py`
- Test: `tests/test_eval_offline.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_eval_offline.py`:

```python
from fleet.eval.offline import predict_records, summarize_offline


def test_predict_records_flags_validity_and_event_type():
    records = [
        {"system": "S", "user": "Event type: traffic\nmore", "assistant": {"action": "reroute"}},
        {"system": "S", "user": "Event type: demand_surge\nx", "assistant": {"action": "reprioritize"}},
    ]

    def complete(system, user):
        if "traffic" in user:
            return {"action": "reroute"}            # matches gold
        return {"action": "not_an_action"}          # invalid

    rows = predict_records(records, complete)
    assert rows[0] == {"pred": "reroute", "gold": "reroute",
                       "event_type": "traffic", "valid": True}
    assert rows[1]["valid"] is False                 # unknown action
    assert rows[1]["event_type"] == "demand_surge"


def test_predict_records_marks_transport_error_invalid():
    records = [{"system": "S", "user": "Event type: traffic\n", "assistant": {"action": "reroute"}}]

    def boom(system, user):
        raise RuntimeError("down")

    rows = predict_records(records, boom)
    assert rows[0]["valid"] is False and rows[0]["pred"] is None


def test_summarize_offline_computes_agreement_validity_confusion():
    rows = [
        {"pred": "reroute", "gold": "reroute", "event_type": "traffic", "valid": True},
        {"pred": "defer", "gold": "reprioritize", "event_type": "demand_surge", "valid": True},
        {"pred": None, "gold": "reroute", "event_type": "traffic", "valid": False},
    ]
    s = summarize_offline(rows)
    assert s["n"] == 3
    assert s["validity_pct"] == 2 / 3
    assert s["agreement_pct"] == 1 / 3            # only the first row agrees
    assert s["confusion"]["traffic"] == {"n": 2, "agree": 1}
    assert s["confusion"]["demand_surge"] == {"n": 1, "agree": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval_offline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.eval'`

- [ ] **Step 3: Write minimal implementation**

Create empty `fleet/eval/__init__.py`:

```python
```

Create `fleet/eval/offline.py`:

```python
"""Offline evaluation (Sovereign Brain v2, M-D): compare a model's predictions to
the oracle-verified gold labels in a held-out JSONL. Pure; the model transport is
injected so this is testable without a GPU or network."""

from fleet.contracts.state import DecisionAction

_VALID_ACTIONS = {a.value for a in DecisionAction}


def _event_type_from_user(user: str) -> str:
    """The user prompt (from build_messages) starts 'Event type: <value>'."""
    first = user.split("\n", 1)[0]
    return first.split("Event type:", 1)[1].strip() if "Event type:" in first else ""


def predict_records(records, complete):
    """Run `complete(system, user) -> dict` over each record and compare its
    action to the record's oracle-verified gold action. Returns rows of
    {pred, gold, event_type, valid}."""
    rows = []
    for rec in records:
        gold = rec["assistant"]["action"]
        event_type = _event_type_from_user(rec["user"])
        try:
            data = complete(rec["system"], rec["user"])
            pred = str(data["action"])
            valid = pred in _VALID_ACTIONS
        except Exception:
            pred, valid = None, False
        rows.append({"pred": pred, "gold": gold,
                     "event_type": event_type, "valid": valid})
    return rows


def summarize_offline(rows) -> dict:
    """Agreement % (valid AND pred==gold), JSON-validity %, per-event confusion."""
    n = len(rows)
    valid = sum(1 for r in rows if r["valid"])
    agree = sum(1 for r in rows if r["valid"] and r["pred"] == r["gold"])
    confusion = {}
    for r in rows:
        d = confusion.setdefault(r["event_type"], {"n": 0, "agree": 0})
        d["n"] += 1
        if r["valid"] and r["pred"] == r["gold"]:
            d["agree"] += 1
    return {
        "n": n,
        "validity_pct": (valid / n) if n else 0.0,
        "agreement_pct": (agree / n) if n else 0.0,
        "confusion": confusion,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_eval_offline.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/eval/__init__.py fleet/eval/offline.py tests/test_eval_offline.py
git commit -m "feat(eval): offline agreement/validity/confusion vs oracle gold"
```

---

### Task 2: Online eval — engine metrics through the loop

**Files:**
- Create: `fleet/eval/online.py`
- Test: `tests/test_eval_online.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_eval_online.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval_online.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.eval.online'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/eval/online.py`:

```python
"""Online evaluation (Sovereign Brain v2, M-D): run a decision engine through the
real headless loop on a fixed scenario and read the realized outcome — on-time %,
cost, delay — plus decision latency. CPU-only and deterministic for rule/scoring."""

import time
from dataclasses import replace

from fleet.contracts.state import WorldState
from fleet.scenarios import build_sample_state
from fleet.factory import build_components
from fleet.loop import run_loop
from fleet.agent.scoring_engine import _Weights
from fleet.agent.oracle import realized_cost


def _silent(*args, **kwargs) -> None:
    pass


def _delay_minutes(state: WorldState) -> float:
    total = 0.0
    for route in state.plan.values():
        for stop in route.stops:
            if stop.actual_arrival is None:
                continue
            cust = state.customers.get(stop.customer_id)
            if cust is None:
                continue
            overdue = (stop.actual_arrival - cust.time_window.end).total_seconds() / 60.0
            if overdue > 0:
                total += overdue
    return total


def _read_metrics(state: WorldState, settings) -> dict:
    delivered = on_time = 0
    for route in state.plan.values():
        for stop in route.stops:
            if stop.actual_arrival is None:
                continue
            delivered += 1
            cust = state.customers.get(stop.customer_id)
            if cust is not None and stop.actual_arrival <= cust.time_window.end:
                on_time += 1
    return {
        "delivered": delivered,
        "on_time": on_time,
        "on_time_pct": (on_time / delivered) if delivered else 0.0,
        "total_delay_min": _delay_minutes(state),
        "total_cost": realized_cost(state, _Weights(settings)),
    }


def engine_metrics(settings, decision_engine, n_ticks: int) -> dict:
    """Run `decision_engine` through the loop on the sample world for n_ticks and
    read the realized outcome. Other components come from the factory; only the
    decision engine is swapped, so the comparison is apples-to-apples."""
    state = build_sample_state()
    components = replace(build_components(settings), decision_engine=decision_engine)
    run_loop(state, components, n_ticks, settings, logger=_silent)
    return _read_metrics(state, settings)


def decide_latency_seconds(decision_engine, state: WorldState, events) -> float:
    """Wall-clock seconds for one decide() call (local NIM vs API round-trip)."""
    start = time.perf_counter()
    decision_engine.decide(state, events)
    return time.perf_counter() - start
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_eval_online.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add fleet/eval/online.py tests/test_eval_online.py
git commit -m "feat(eval): online engine metrics (on-time/cost/delay) + decide latency"
```

---

### Task 3: Training driver `train_lora.py` (+ pure `format_chat_example`)

**Files:**
- Create: `scripts/train_lora.py`
- Test: `tests/test_train_lora.py`

Only `format_chat_example` and `parse_args` are unit-tested (no GPU). The training itself runs on the H200s (covered by the runbook). All heavy imports live inside `main()` so importing the module for the test needs no `torch`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_train_lora.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_train_lora.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.train_lora'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/train_lora.py`:

```python
"""LoRA fine-tune the base model on the oracle-verified dataset (Sovereign Brain
v2, M-D). Heavy GPU imports (torch/transformers/trl/peft) live inside main() so
the pure formatter is importable and testable without a GPU.

Run on the H200s:
  python -m scripts.train_lora --train data/sovereign-brain/train.jsonl \
      --out /raid/team/adapters/sovereign-brain
"""

import argparse
import json


def format_chat_example(record: dict) -> dict:
    """One JSONL row -> a chat example for SFTTrainer. The assistant turn is the
    strict decision JSON, so train-time output matches the served _DECISION_SCHEMA."""
    return {"messages": [
        {"role": "system", "content": record["system"]},
        {"role": "user", "content": record["user"]},
        {"role": "assistant",
         "content": json.dumps(record["assistant"], ensure_ascii=False)},
    ]}


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--train", required=True, help="train.jsonl from gen_dataset")
    p.add_argument("--out", default="/raid/team/adapters/sovereign-brain")
    p.add_argument("--base-model", dest="base_model",
                   default="nvidia/Llama-3.1-Nemotron-Nano-8B-v1")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch", type=int, default=4)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--lora-r", dest="lora_r", type=int, default=16)
    p.add_argument("--lora-alpha", dest="lora_alpha", type=int, default=32)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


def _load_examples(path):
    with open(path, "r", encoding="utf-8") as f:
        return [format_chat_example(json.loads(line)) for line in f if line.strip()]


def main():
    args = parse_args()

    import torch
    from datasets import Dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig
    from trl import SFTTrainer, SFTConfig

    ds = Dataset.from_list(_load_examples(args.train))
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model, torch_dtype=torch.bfloat16, device_map="auto")

    peft_config = LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.05,
        task_type="CAUSAL_LM", target_modules="all-linear")
    sft_config = SFTConfig(
        output_dir=args.out, num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch, learning_rate=args.lr,
        bf16=True, logging_steps=10, save_strategy="epoch", seed=args.seed)

    trainer = SFTTrainer(
        model=model, args=sft_config, train_dataset=ds,
        peft_config=peft_config, processing_class=tokenizer)
    trainer.train()
    trainer.save_model(args.out)
    print(f"adapter saved to {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_train_lora.py -v`
Expected: PASS (2 tests — neither imports torch)

- [ ] **Step 5: Commit**

```bash
git add scripts/train_lora.py tests/test_train_lora.py
git commit -m "feat(train): LoRA SFT driver + pure chat formatter (GPU imports lazy)"
```

---

### Task 4: `eval_brain.py` CLI (offline + online + report)

**Files:**
- Create: `scripts/eval_brain.py`
- Test: `tests/test_eval_brain.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_eval_brain.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval_brain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.eval_brain'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/eval_brain.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_eval_brain.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_brain.py tests/test_eval_brain.py
git commit -m "feat(eval): eval_brain CLI — offline agreement + online engine comparison"
```

---

### Task 5: Regression + smoke

**Files:**
- No code changes — verifies the milestone is purely additive (eval/train are offline; the loop and default path are untouched; the suite stays GPU/network-free).

- [ ] **Step 1: Run the whole suite**

Run: `pytest -q`
Expected: PASS — the prior count plus the new tests (3 in `test_eval_offline.py`, 2 in `test_eval_online.py`, 2 in `test_train_lora.py`, 2 in `test_eval_brain.py`). No previously-passing test changes status; neither `torch` nor `openai` is imported by the suite.

- [ ] **Step 2: Smoke the offline+online eval ($0, no GPU)**

Run: `python -m scripts.eval_brain --ticks 8`
Expected: prints a JSON report with an `online` block comparing `rule` and `scoring` (each with `on_time_pct`, `total_cost`, `total_delay_min`). No `--test`/`--nim-endpoint`, so no offline section and no network — pure CPU.

- [ ] **Step 3: Commit (only if an incidental fix was needed; otherwise skip)**

This task is a verification gate; if `pytest -q` and the smoke were already green, there is nothing to commit.

---

## Self-Review

**Spec coverage (vs `2026-06-07-sovereign-brain-v2-oracle-design.md` §4.6, §6, §10 M-D):**
- §4.6 LoRA SFT on the base model, multi-GPU H200, adapter saved, seed+config reproducible → Task 3 (`train_lora.py`: `SFTTrainer`+`LoraConfig`, `device_map="auto"`, `seed`, `save_model`). ✓
- §6 offline (action-agreement vs **oracle ground-truth**, JSON-validity, per-event confusion) → Tasks 1, 4. ✓
- §6 online (NimAgent vs ClaudeAgent vs RuleBasedEngine vs ScoringEngine on on-time %, cost/delay, **decision latency**) → Task 2 (`engine_metrics`, `decide_latency_seconds`) + Task 4 (`run_online`, NIM behind `--nim-endpoint`). The Claude engine slots in the same way as NIM (build it and call `engine_metrics`); the harness is engine-agnostic. ✓
- §6 "beat-the-teacher" headline → the online block reports on-time % per engine side-by-side, surfacing whether the oracle-trained NIM exceeds Claude — Task 4 report. ✓
- §7 boundary: eval/train are offline; only `train_lora.py` needs a GPU and keeps those imports inside `main()`; the suite imports neither `torch` nor `openai`; the loop/default path is untouched → Tasks 1–5. ✓
- §10 M-D "LoRA fine-tuned, adapter served via NIM, eval offline+online with headline numbers" → Task 3 (train) + Task 4 (eval); serving the adapter via NIM multi-LoRA is an ops step in the runbook (point `--nim-endpoint` at the adapter-loaded NIM). ✓

**Data-quality gate (carried from M-B):** the M-B smoke showed a low informative-fraction at small seed counts. Before training, run `python -m scripts.gen_dataset --seeds 200 --out data/sovereign-brain` and check the report's `event_types` coverage. If it is too narrow (1–2 event types), broaden it before `train_lora.py` — the documented lever is the oracle `resolve` re-solve hook (spec stretch) so REROUTE/RESCHEDULE/REPRIORITIZE become consequential. This belongs in the runbook as a pre-train checkpoint, not a code task here.

**Placeholder scan:** No TBD/TODO; every code step is complete; every command has expected output.

**Type consistency:** `predict_records(records, complete) -> rows` and `summarize_offline(rows) -> dict` (Task 1) are exactly what `run_offline` calls (Task 4). `engine_metrics(settings, decision_engine, n_ticks) -> dict` (Task 2) is what `run_online` calls per engine (Task 4). `format_chat_example(record) -> {"messages": [...]}` (Task 3) consumes the M-B JSONL row shape `{system, user, assistant{action,reasoning,added_delay_min}}` and is reused by `_load_examples`. The offline predictor contract `complete(system, user) -> dict` matches `NimAgent._get_complete()` (M-C) and `rule_predictor()`. Reuses `realized_cost`/`_Weights` (M-A/M-D) and `run_loop`/`build_components` without changing them.

**Dependencies:** M-A (`realized_cost`), M-B (the JSONL + `build_record` used in the test), M-C (`NimAgent` transport for the real model) — all merged. The required DoD (Tasks 1, 2, 4, 5 + `format_chat_example`) is CPU-only; the actual LoRA run and adapter-serving happen on the H200s per the runbook.
