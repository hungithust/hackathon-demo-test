"""Scale benchmark: how many independent simulation sessions a box can host.

Measures, for the *sample* world (the default demo problem):
  - build time per SimulationController (one independent world)
  - RAM per session (process RSS delta)
  - step() latency (solve VRPTW + advance one tick)
  - serial single-core throughput (steps/sec)
  - parallel throughput across local cores (does OR-Tools release the GIL?)

Then extrapolates to the target box (192 cores / 2 TB RAM).
Run:  python bench_scale.py
"""
import gc
import os
import time
import statistics
from concurrent.futures import ThreadPoolExecutor

import psutil

from fleet.ui.controller import SimulationController

PROC = psutil.Process(os.getpid())
LOCAL_CORES = os.cpu_count() or 1
TARGET_CORES = 192
TARGET_RAM_GB = 2048


def rss_mb():
    return PROC.memory_info().rss / 1e6


def time_it(fn, n=1):
    t = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t) / n


def main():
    print(f"== Local box: {LOCAL_CORES} cores ==\n")

    # ---- 1. build time + RAM per session ----------------------------------
    gc.collect()
    base_rss = rss_mb()
    N = 50
    t0 = time.perf_counter()
    ctrls = [SimulationController() for _ in range(N)]
    build_total = time.perf_counter() - t0
    gc.collect()
    after_rss = rss_mb()

    build_ms = build_total / N * 1000
    ram_per = (after_rss - base_rss) / N
    print(f"[build]  {N} sessions in {build_total:.2f}s  ->  {build_ms:.1f} ms/session")
    print(f"[ram]    +{after_rss - base_rss:.0f} MB total  ->  {ram_per:.2f} MB/session")

    # ---- 2. step() latency (single core, serial) --------------------------
    c = ctrls[0]
    c.step(1)  # warm up (jit caches, etc.)
    lat = [time_it(lambda: c.step(1)) for _ in range(20)]
    p50 = statistics.median(lat) * 1000
    p95 = sorted(lat)[int(len(lat) * 0.95)] * 1000
    mean = statistics.mean(lat) * 1000
    print(f"\n[step]   mean {mean:.1f} ms  | p50 {p50:.1f} ms  | p95 {p95:.1f} ms")
    serial_sps = 1000.0 / mean
    print(f"[serial] 1 core sustains ~{serial_sps:.1f} steps/sec")

    # ---- 3. snapshot cost -------------------------------------------------
    snap = time_it(lambda: c.snapshot(), n=20) * 1000
    print(f"[snap]   snapshot() {snap:.1f} ms each")

    # ---- 4. parallel throughput across local cores ------------------------
    # Each thread steps its own controller -> tests real parallelism (GIL).
    work = ctrls[:LOCAL_CORES]
    for w in work:
        w.step(1)  # warm

    def beat(ctrl):
        for _ in range(10):
            ctrl.step(1)
        return 10

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=LOCAL_CORES) as ex:
        done = sum(ex.map(beat, work))
    par_dt = time.perf_counter() - t0
    par_sps = done / par_dt
    speedup = par_sps / serial_sps
    print(f"\n[par]    {LOCAL_CORES} threads -> {par_sps:.0f} steps/sec "
          f"(speedup {speedup:.1f}x vs 1 core)")
    eff = speedup / LOCAL_CORES
    print(f"[par]    parallel efficiency {eff*100:.0f}% "
          f"(GIL released during solve: {'yes' if eff > 0.5 else 'limited'})")

    # ---- 5. extrapolate to target box -------------------------------------
    print(f"\n== Extrapolation to target box ({TARGET_CORES} cores / {TARGET_RAM_GB} GB) ==")
    # Throughput-bound: scale measured per-core sustained rate by core count * eff.
    box_sps = serial_sps * TARGET_CORES * eff
    print(f"[cpu]    ~{box_sps:,.0f} steps/sec aggregate (CpuSolver, sample world)")

    # How many *active* users (each issuing a step every T seconds) can be served?
    for T in (2, 5, 10):
        users = box_sps * T
        print(f"         if each active user steps every {T}s -> ~{users:,.0f} concurrent active users")

    # RAM-bound session count (cap sessions to 70% of RAM for headroom).
    ram_sessions = (TARGET_RAM_GB * 1024 * 0.7) / max(ram_per, 0.01)
    print(f"[ram]    ~{ram_sessions:,.0f} resident sessions fit in 70% of {TARGET_RAM_GB} GB "
          f"(@ {ram_per:.2f} MB/session)")

    print("\nNote: numbers are for the SMALL sample world (10 veh/10 cust). "
          "Real OSM worlds with more stops/edges cost more per step & per MB; "
          "GPU (cuOpt/NIM) not exercised here.")


if __name__ == "__main__":
    main()
