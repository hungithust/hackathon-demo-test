"""CPU (OR-Tools) vs GPU (NVIDIA cuOpt) benchmark for the fleet optimizer.

Runs three comparisons and writes the raw numbers to bench/results.json so the
plotting script (bench/plot_results.py) never has to re-run the (slow) solves:

  A. Single-depot scaling   — 1 depot, customers = {10,25,50,100,200}
  B. Multi-depot scaling     — 5 depots, same customer counts
  C. 1000-user concurrency   — throughput / wall-clock to clear 1000 solve
                               requests on each engine

For A & B we record, per engine and size:
  - solve latency (ms)            -> "how fast"
  - total route time (min)        -> "how optimal" (lower = better plan)
  - served / dropped tasks        -> feasibility

cuOpt is the REAL self-hosted NIM at settings.cuopt_endpoint (default
localhost:8001). CPU is OR-Tools with the system's default config. Numbers are
measured on whatever box you run this on; the 1000-user figures combine measured
per-request cost with measured parallelism (see notes in the JSON).

Run:  python -m bench.run_benchmark            (full; cuOpt is slow ~20s/solve)
      python -m bench.run_benchmark --cpu-only (skip the GPU, seconds to finish)
"""

import argparse
import json
import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from bench.problem_gen import make_problem
from bench.cuopt_transport import make_transport
from fleet.routing.cpu_solver import CpuSolver
from fleet.routing.cuopt_adapter import CuOptAdapter

RESULTS = os.path.join(os.path.dirname(__file__), "results.json")
SIZES = [10, 25, 50, 100, 200]
LOCAL_CORES = os.cpu_count() or 1


def _solve_timed(solver, problem):
    t = time.perf_counter()
    sol = solver.solve(problem)
    dt = (time.perf_counter() - t) * 1000.0
    m = sol.metrics
    return {
        "latency_ms": dt,
        "total_time_min": float(m.get("total_time_min", 0.0)),
        "served": int(m.get("served", 0)),
        "dropped": int(m.get("dropped", 0)),
        "feasible": bool(sol.feasible),
    }


def scaling(engine, solver, n_depots, sizes, seeds):
    """Sweep problem sizes for one engine at a fixed depot count."""
    rows = []
    for n in sizes:
        runs = [_solve_timed(solver, make_problem(n, n_depots, seed=s))
                for s in range(seeds)]
        rows.append({
            "n_customers": n,
            "latency_ms": statistics.mean(r["latency_ms"] for r in runs),
            "total_time_min": statistics.mean(r["total_time_min"] for r in runs),
            "served": runs[0]["served"],
            "dropped": runs[0]["dropped"],
        })
        r = rows[-1]
        print(f"  [{engine} d={n_depots} n={n:>4}] "
              f"{r['latency_ms']:>9.1f} ms | route {r['total_time_min']:>6.0f} min "
              f"| served {r['served']}/{n}")
    return rows


def concurrency(cpu, cuopt, n_users=1000, probe=20):
    """Estimate wall-clock to clear `n_users` independent solve requests.

    CPU: measure single-core solve cost + real multi-core parallel efficiency
    (does OR-Tools release the GIL?), then n_users / aggregate_throughput.
    cuOpt: one GPU server services requests near-serially; measure effective
    concurrency from a small parallel probe, then extrapolate."""
    out = {"n_users": n_users, "probe_problem": probe, "local_cores": LOCAL_CORES}

    # ---- CPU: serial cost + parallel efficiency --------------------------
    p = make_problem(probe, 1, seed=0)
    cpu.solve(p)  # warm
    serial = statistics.mean(_solve_timed(cpu, p)["latency_ms"] for _ in range(10)) / 1000.0
    ctrls = [(CpuSolver(), make_problem(probe, 1, seed=i)) for i in range(LOCAL_CORES)]

    def burst(pair):
        s, pr = pair
        for _ in range(5):
            s.solve(pr)
        return 5

    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=LOCAL_CORES) as ex:
        done = sum(ex.map(burst, ctrls))
    par_solves = done / (time.perf_counter() - t)
    eff = (par_solves / (1.0 / serial)) / LOCAL_CORES
    out["cpu"] = {
        "serial_solve_s": serial,
        "parallel_solves_per_s": par_solves,
        "parallel_efficiency": eff,
        "wall_s_1000": n_users / par_solves,
        "note": "OR-Tools across all local cores; scales ~linearly with more cores/processes.",
    }
    print(f"  [CPU] serial {serial*1000:.0f} ms/solve | {par_solves:.0f} solves/s "
          f"on {LOCAL_CORES} cores (eff {eff*100:.0f}%) -> {n_users} users in "
          f"{out['cpu']['wall_s_1000']:.1f}s")

    # ---- cuOpt: per-request cost + effective concurrency -----------------
    if cuopt is not None:
        lat = _solve_timed(cuopt, p)["latency_ms"] / 1000.0  # warm-ish single
        K = 4

        def one(i):
            t0 = time.perf_counter()
            cuopt.solve(make_problem(probe, 1, seed=i))
            return time.perf_counter() - t0

        t = time.perf_counter()
        with ThreadPoolExecutor(max_workers=K) as ex:
            list(ex.map(one, range(K)))
        wall_k = time.perf_counter() - t
        eff_conc = (K * lat) / wall_k  # >1 => server overlaps work
        thr = eff_conc / lat           # effective solves/sec
        out["cuopt"] = {
            "serial_solve_s": lat,
            "effective_concurrency": eff_conc,
            "solves_per_s": thr,
            "wall_s_1000": n_users / thr,
            "note": "single self-hosted cuOpt GPU server; requests queue, so "
                    "throughput is ~1 GPU regardless of client threads.",
        }
        print(f"  [cuOpt] {lat:.1f} s/solve | eff-concurrency {eff_conc:.2f} | "
              f"{thr:.2f} solves/s -> {n_users} users in "
              f"{out['cuopt']['wall_s_1000']:.0f}s")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cpu-only", action="store_true")
    ap.add_argument("--cpu-seeds", type=int, default=3)
    ap.add_argument("--gpu-seeds", type=int, default=1)
    ap.add_argument("--time-limit", type=float, default=1.0,
                    help="cuOpt GPU solver internal time_limit (s)")
    args = ap.parse_args()

    cpu = CpuSolver()
    cuopt = None
    if not args.cpu_only:
        cuopt = CuOptAdapter(transport=make_transport(time_limit=args.time_limit))

    data = {"meta": {
        "cores": LOCAL_CORES, "sizes": SIZES, "cuopt": not args.cpu_only,
        "cpu_engine": "OR-Tools (PATH_CHEAPEST_ARC default)",
        "gpu_engine": "NVIDIA cuOpt NIM 25.12 (self-hosted)",
    }}

    print("== A. Single-depot scaling (1 depot) ==")
    data["single_depot"] = {
        "cpu": scaling("CPU", cpu, 1, SIZES, args.cpu_seeds),
        "cuopt": scaling("cuOpt", cuopt, 1, SIZES, args.gpu_seeds) if cuopt else None,
    }
    print("== B. Multi-depot scaling (5 depots) ==")
    data["multi_depot"] = {
        "cpu": scaling("CPU", cpu, 5, SIZES, args.cpu_seeds),
        "cuopt": scaling("cuOpt", cuopt, 5, SIZES, args.gpu_seeds) if cuopt else None,
    }
    print("== C. 1000-user concurrency ==")
    data["concurrency"] = concurrency(cpu, cuopt)

    with open(RESULTS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\nWrote {RESULTS}")


if __name__ == "__main__":
    main()