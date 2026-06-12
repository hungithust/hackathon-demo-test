"""Solve-cost benchmark: the EXPENSIVE path (full VRPTW solve / reroute), and
whether OR-Tools releases the GIL so 192 cores actually buy parallelism.

The quiet-tick step() is ~0.1ms (no solving) and misleads. What costs CPU is a
plan_routes / reroute solve. We measure that unit and its parallel efficiency.
"""
import io
import os
import time
import statistics
import contextlib
from concurrent.futures import ThreadPoolExecutor

from fleet.ui.controller import SimulationController
from fleet.routing import planner

LOCAL_CORES = os.cpu_count() or 1
TARGET_CORES = 192


def fresh_ctrl():
    return SimulationController()


def solve_once(c):
    # Full VRPTW solve from scratch — the heavy CPU unit. (plan_routes is silent;
    # the noisy prints live in the reroute path, not here.)
    planner.plan_routes(c.state, c.components.optimizer)


def main():
    print(f"== Local box: {LOCAL_CORES} cores ==\n")
    c = fresh_ctrl()
    solve_once(c)  # warm

    # ---- serial solve latency --------------------------------------------
    lat = []
    for _ in range(30):
        t = time.perf_counter()
        solve_once(c)
        lat.append((time.perf_counter() - t) * 1000)
    mean = statistics.mean(lat)
    p50 = statistics.median(lat)
    p95 = sorted(lat)[int(len(lat) * 0.95)]
    print(f"[solve]  full VRPTW (10 veh/10 cust): mean {mean:.2f} ms | "
          f"p50 {p50:.2f} | p95 {p95:.2f}")
    serial_solves = 1000.0 / mean
    print(f"[serial] 1 core: ~{serial_solves:.0f} solves/sec")

    # ---- parallel efficiency on the heavy unit ---------------------------
    ctrls = [fresh_ctrl() for _ in range(LOCAL_CORES)]
    for c in ctrls:
        solve_once(c)  # warm
    K = 40

    def burst(ctrl):
        for _ in range(K):
            solve_once(ctrl)
        return K

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=LOCAL_CORES) as ex:
        done = sum(ex.map(burst, ctrls))
    dt = time.perf_counter() - t0
    par_solves = done / dt
    speedup = par_solves / serial_solves
    eff = speedup / LOCAL_CORES
    print(f"\n[par]    {LOCAL_CORES} threads -> {par_solves:.0f} solves/sec "
          f"(speedup {speedup:.1f}x, efficiency {eff*100:.0f}%)")
    print(f"[gil]    OR-Tools releases GIL during solve: "
          f"{'YES — real multi-core scaling' if eff > 0.5 else 'NO — GIL-bound, need multi-PROCESS workers'}")

    # ---- extrapolate ------------------------------------------------------
    # Conservative: if GIL-bound (eff low) you must use processes; a 192-core box
    # then gives ~192x serial via 192 worker processes (near-linear, sep. memory).
    proc_solves = serial_solves * TARGET_CORES  # multi-process ceiling
    thread_solves = serial_solves * TARGET_CORES * eff  # if you stayed single-process
    print(f"\n== Target box ({TARGET_CORES} cores) aggregate solve capacity ==")
    print(f"[multiproc] ~{proc_solves:,.0f} solves/sec  (192 worker processes — the way to go)")
    print(f"[threads ] ~{thread_solves:,.0f} solves/sec  (single process — wasted if GIL-bound)")

    # A reroute happens only on a disruption, not every tick. Assume a busy user
    # triggers, say, 1 real solve every ~20s of wall-clock interaction.
    for per_user_interval in (10, 20, 60):
        users = proc_solves * per_user_interval
        print(f"            if 1 solve / {per_user_interval}s per active user "
              f"-> ~{users:,.0f} concurrent active users (solve-bound)")


if __name__ == "__main__":
    main()