"""Offline data factory for Sovereign Brain v2 (M-B). Drives the simulator over
seeded scenarios, grades candidate actions with the oracle, keeps informative
oracle-verified labels, attaches reasoning (templated $0 by default, or Sonnet
Batch with --use-teacher), and writes seed-split train/test JSONL.

Usage:
  python -m scripts.gen_dataset --seeds 200 --out data/sovereign-brain
  python -m scripts.gen_dataset --seeds 200 --out data/sovereign-brain --use-teacher
"""

import argparse
import json
import os

from config.settings import load_settings
from fleet.factory import build_components
from fleet.agent.dataset import (
    iter_examples, grade_example, is_informative, build_record, batch_reasoning,
    split_by_seed, default_batch_submit,
)


def build_dataset(settings, n_seeds, out_dir, holdout_frac=0.2, use_teacher=False):
    """Generate the dataset and write {train,test}.jsonl under out_dir. Returns a
    report dict (counts, informative fraction, per-event-type coverage)."""
    optimizer = build_components(settings).optimizer

    graded = []          # (seed, state, event, action, delay, scored)
    n_total = 0
    for seed, (sim, state, event) in iter_examples(settings, n_seeds, optimizer):
        n_total += 1
        action, delay, scored = grade_example(sim, state, event, settings)
        if is_informative(scored, settings.oracle_min_gap):
            graded.append((seed, state, event, action, delay, scored))

    # reasoning (teacher or $0 templated), keyed by a stable custom_id
    examples = [{"custom_id": f"ex-{i}", "state": st, "event": ev,
                 "action": ac, "scored": sc}
                for i, (_seed, st, ev, ac, _dl, sc) in enumerate(graded)]
    submit = default_batch_submit(settings) if use_teacher else None
    reasonings = batch_reasoning(examples, submit=submit)

    records = []         # (seed, record)
    for i, (seed, st, ev, ac, dl, _sc) in enumerate(graded):
        rec = build_record(st, ev, ac, dl, reasonings[f"ex-{i}"])
        records.append((seed, rec))

    train, test = split_by_seed(records, holdout_frac)

    os.makedirs(out_dir, exist_ok=True)
    _write_jsonl(os.path.join(out_dir, "train.jsonl"), train)
    _write_jsonl(os.path.join(out_dir, "test.jsonl"), test)

    coverage = {}
    for _seed, _st, ev, _ac, _dl, _sc in graded:
        coverage[ev.event_type.value] = coverage.get(ev.event_type.value, 0) + 1

    return {
        "n_total": n_total,
        "n_informative": len(graded),
        "informative_fraction": (len(graded) / n_total) if n_total else 0.0,
        "n_train": len(train),
        "n_test": len(test),
        "event_types": coverage,
    }


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=200)
    p.add_argument("--out", default="data/sovereign-brain")
    p.add_argument("--holdout-frac", type=float, default=0.2)
    p.add_argument("--use-teacher", action="store_true",
                   help="label reasoning via Sonnet 4.6 Batch (needs ANTHROPIC_API_KEY)")
    args = p.parse_args()

    report = build_dataset(load_settings(), args.seeds, args.out,
                           args.holdout_frac, args.use_teacher)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
