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
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

from config.settings import load_settings
from fleet.factory import build_components
from fleet.agent.dataset import (
    iter_examples, grade_full, is_informative, build_record, batch_reasoning,
    split_by_seed, default_batch_submit, build_preference_record, templated_reasoning,
    iter_disrupted_examples, grade_disrupted,
    DATASET_EVENT_SPECS, DISRUPTED_EVENT_SPECS, make_example, make_disrupted_example,
)


def build_dataset(settings, n_seeds, out_dir, holdout_frac=0.2, use_teacher=False,
                  dpo=False, consequential=False, workers=1):
    """Generate the dataset and write {train,test}.jsonl (and prefs.jsonl when dpo)
    under out_dir. Returns a report dict (counts, informative fraction, coverage)."""
    workers = max(1, int(workers or 1))
    graded, n_total = _collect_graded_examples(settings, n_seeds, consequential, workers)

    examples = [{"custom_id": f"ex-{i}", "state": st, "event": ev,
                 "action": full[0][0], "scored": [(a, c) for a, c, _ in full]}
                for i, (_seed, st, ev, full) in enumerate(graded)]
    submit = default_batch_submit(settings) if use_teacher else None
    reasonings = batch_reasoning(examples, submit=submit)

    records = []         # (seed, record)
    prefs = []           # preference rows (no seed split needed for DPO)
    for i, (seed, st, ev, full) in enumerate(graded):
        reasoning = reasonings[f"ex-{i}"]
        best_a, _bc, best_d = full[0]
        records.append((seed, build_record(st, ev, best_a, best_d, reasoning)))
        if dpo:
            prefs.append(build_preference_record(st, ev, full, reasoning))

    train, test = split_by_seed(records, holdout_frac)

    os.makedirs(out_dir, exist_ok=True)
    _write_jsonl(os.path.join(out_dir, "train.jsonl"), train)
    _write_jsonl(os.path.join(out_dir, "test.jsonl"), test)
    if dpo:
        _write_jsonl(os.path.join(out_dir, "prefs.jsonl"), prefs)

    coverage = {}
    for _seed, _st, ev, _full in graded:
        coverage[ev.event_type.value] = coverage.get(ev.event_type.value, 0) + 1

    return {
        "n_total": n_total,
        "n_informative": len(graded),
        "informative_fraction": (len(graded) / n_total) if n_total else 0.0,
        "n_train": len(train),
        "n_test": len(test),
        "n_prefs": len(prefs),
        "event_types": coverage,
        "consequential": consequential,
        "workers": workers,
        "routing_engine": settings.routing_engine,
        "consequential_min_horizon_ticks": int(
            getattr(settings, "consequential_min_horizon_ticks", 60) or 60),
    }


def _collect_graded_examples(settings, n_seeds, consequential, workers):
    optimizer = build_components(settings).optimizer
    if workers <= 1:
        graded = []
        n_total = 0
        example_iter = (iter_disrupted_examples(settings, n_seeds, optimizer)
                        if consequential else
                        iter_examples(settings, n_seeds, optimizer))
        for seed, (sim, state, event) in example_iter:
            n_total += 1
            full = (grade_disrupted(sim, state, event, settings, optimizer)
                    if consequential else
                    grade_full(sim, state, event, settings))
            scored = [(a, c) for a, c, _d in full]
            if is_informative(scored, settings.oracle_min_gap):
                graded.append((seed, state, event, full))
        return graded, n_total

    specs = DISRUPTED_EVENT_SPECS if consequential else DATASET_EVENT_SPECS
    tasks = [
        (settings, seed, spec, consequential)
        for seed in range(settings.seed, settings.seed + n_seeds)
        for spec in specs
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_grade_task, tasks))
    graded = [r for r in results if r is not None]
    return graded, len(tasks)


def _grade_task(args):
    settings, seed, spec, consequential = args
    optimizer = build_components(settings).optimizer
    if consequential:
        sim, state, event = make_disrupted_example(seed, spec, settings, optimizer)
        full = grade_disrupted(sim, state, event, settings, optimizer)
    else:
        sim, state, event = make_example(seed, spec, settings, optimizer)
        full = grade_full(sim, state, event, settings)
    scored = [(a, c) for a, c, _d in full]
    if not is_informative(scored, settings.oracle_min_gap):
        return None
    return seed, state, event, full


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=200)
    p.add_argument("--out", default="data/sovereign-brain")
    p.add_argument("--holdout-frac", type=float, default=0.2)
    p.add_argument("--workers", type=int, default=1,
                   help="parallel grading workers; start with CPU core count on dataset nodes")
    p.add_argument("--dataset-routing-engine", choices=("cpu", "cuopt", "inherit"),
                   default="cpu",
                   help="routing engine for offline dataset grading; defaults to cpu to avoid per-solve network overhead")
    p.add_argument("--consequential-horizon-min", type=int, default=None,
                   help="override minimum grading horizon for consequential path (default: settings/env, usually 60)")
    p.add_argument("--use-teacher", action="store_true",
                   help="label reasoning via Sonnet 4.6 Batch (needs ANTHROPIC_API_KEY)")
    p.add_argument("--dpo", action="store_true",
                   help="also emit prefs.jsonl (oracle best/worst preference pairs)")
    p.add_argument("--consequential", action="store_true",
                   help="use the M-F consequential-disruptions path for oracle grading")
    args = p.parse_args()

    settings = load_settings()
    if args.dataset_routing_engine != "inherit":
        settings = replace(settings, routing_engine=args.dataset_routing_engine)
    if args.consequential_horizon_min is not None:
        settings = replace(settings,
                           consequential_min_horizon_ticks=args.consequential_horizon_min)

    report = build_dataset(settings, args.seeds, args.out,
                           args.holdout_frac, args.use_teacher, args.dpo,
                           args.consequential or os.environ.get(
                               "CONSEQUENTIAL_DISRUPTIONS", "0") in ("1", "true", "True"),
                           args.workers)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
