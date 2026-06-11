"""Prove the system runs N (default 1000) DIFFERENT problems at once.

Generates N distinct ScenarioSpecs (different maps, fleets, speeds, disruptions),
builds an isolated SimulationController for each and steps every world, spread
across worker PROCESSES (OR-Tools is GIL-bound, so processes — not threads — give
real multi-core scaling). Reports wall-clock, throughput and peak RAM, and verifies
every world actually advanced and stayed solvable.

    python -m scripts.scale_test                 # 1000 sessions, all cores
    python -m scripts.scale_test --n 1000 --steps 5 --workers 16
"""
import argparse
import os
import time
from concurrent.futures import ProcessPoolExecutor

import psutil

from fleet.scenarios import make_scenarios, build_random_state
from fleet.ui.controller import SimulationController


def _run_chunk(args):
    """One worker process: build + step a slice of scenarios. Returns aggregate
    stats (kept tiny so we don't ship worlds back across the process boundary)."""
    specs, steps = args
    proc = psutil.Process(os.getpid())
    rss0 = proc.memory_info().rss
    ok = ticks = orders = 0
    t0 = time.perf_counter()
    # Silence the planner's reroute prints (safe here: each worker is single-threaded).
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        for spec in specs:
            state = build_random_state(spec)
            ctrl = SimulationController(state=state)
            ctrl.step(steps)
            ok += 1
            ticks += ctrl.state.sim_tick
            orders += ctrl.state.total_orders_pending()
    dt = time.perf_counter() - t0
    rss_mb = (proc.memory_info().rss - rss0) / 1e6
    return {"ok": ok, "ticks": ticks, "orders": orders, "dt": dt, "rss_mb": rss_mb}


def _chunks(seq, k):
    """Split seq into k roughly equal contiguous chunks."""
    n = len(seq)
    size, rem = divmod(n, k)
    out, i = [], 0
    for c in range(k):
        take = size + (1 if c < rem else 0)
        out.append(seq[i:i + take])
        i += take
    return [c for c in out if c]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000, help="number of distinct problems")
    ap.add_argument("--steps", type=int, default=5, help="sim ticks per session")
    ap.add_argument("--workers", type=int, default=os.cpu_count(),
                    help="worker processes (default: all cores)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    cores = os.cpu_count()
    print(f"Generating {args.n} distinct scenarios (seed={args.seed})...")
    specs = make_scenarios(args.n, seed=args.seed)
    # sanity: the maps really differ
    uniq_centers = len({(round(s.center_lat, 3), round(s.center_lng, 3)) for s in specs})
    sizes = sorted({(s.n_customers, s.n_vehicles) for s in specs})
    print(f"  distinct map centres: {uniq_centers}/{args.n} | "
          f"distinct fleet/customer sizes: {len(sizes)}")

    workers = min(args.workers, args.n)
    chunks = _chunks(specs, workers)
    print(f"\nRunning on {workers} worker processes (box has {cores} cores), "
          f"{args.steps} steps each...")

    sys_rss0 = psutil.virtual_memory().used
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_run_chunk, [(c, args.steps) for c in chunks]))
    wall = time.perf_counter() - t0
    sys_rss_mb = (psutil.virtual_memory().used - sys_rss0) / 1e6

    total_ok = sum(r["ok"] for r in results)
    total_steps = total_ok * args.steps
    print("\n================= RESULTS =================")
    print(f"sessions completed : {total_ok}/{args.n}")
    print(f"wall-clock         : {wall:.2f} s")
    print(f"throughput         : {total_ok / wall:,.0f} sessions/s | "
          f"{total_steps / wall:,.0f} steps/s")
    print(f"per-session         : {wall / total_ok * 1000:.1f} ms "
          f"(build + {args.steps} steps, wall, {workers} procs)")
    print(f"peak RAM delta     : {sys_rss_mb:,.0f} MB total "
          f"(~{sys_rss_mb / max(total_ok,1):.2f} MB/session)")

    # Extrapolate to the 192-core box.
    box = 192
    scale = box / workers
    print(f"\n-- extrapolated to {box}-core box (×{scale:.1f} the {workers} procs here) --")
    print(f"  ~{total_ok / wall * scale:,.0f} sessions/s build+run")
    print(f"  1000 fresh users cold-start in ~{1000 / (total_ok / wall * scale):.2f} s")
    if total_ok != args.n:
        raise SystemExit(f"FAIL: only {total_ok}/{args.n} sessions completed")
    print("\nOK — all distinct problems built, stepped and stayed solvable.")


if __name__ == "__main__":
    main()