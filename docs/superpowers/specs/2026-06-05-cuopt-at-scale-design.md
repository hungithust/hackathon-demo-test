# cuOpt at Scale — GPU routing the CPU can't keep up with

> Version: 1.0 · Date: 2026-06-05
> Status: design approved, awaiting spec review
> Scope: ONE of three competition-upgrade specs (others: Sovereign Brain, demo polish).
> Context: NVIDIA Open Hackathon 2026 (Viettel × NVIDIA), 8× H200. Judging weights:
> NVIDIA-stack usage, business impact/demo, technical novelty.

---

## 0. One sentence

Prove, with real H200 numbers, that the fleet's VRP optimization genuinely needs the GPU —
by generating realistic supply networks that grow to thousands of nodes/vehicles and showing
that under the same wall-clock budget the CPU OR-Tools solver degrades or stalls while
NVIDIA **cuOpt** keeps solving fast and well.

## 1. Why this is in scope

- **Cheap, high ROI.** `CuOptAdapter` and `CpuSolver` are already interface-twins behind
  `RouteOptimizer`, both consuming the same `RoutingProblem` — the benchmark swaps solvers
  with zero glue. Most of the work is *generating scale*, not new solver code.
- **NVIDIA stack + realtime/scale axes.** Directly substantiates the "realtime at scale"
  and "uses the GPU meaningfully" claims with a chart judges can read in five seconds.

## 2. Honest framing (must stay in the pitch)

At the live *demo* scale (one depot, a handful of customers) OR-Tools is instant — cuOpt's
advantage appears only **at scale and/or under a tight time budget**. OR-Tools is a genuinely
strong solver at small/medium sizes. The deliverable is therefore a **benchmark that creates
the scale** where the GPU wins, reported honestly: same time budget, compare solution quality
and solve time as N grows. No "cuOpt always beats OR-Tools" overclaim.

## 3. Decisions locked

| Decision | Choice | Why |
|---|---|---|
| Problem generation | **Full road-graph `WorldState`** → reuse `build_routing_problem` | end-to-end realistic (real graph, flood/blocked edges, veh-type wade), not a synthetic toy |
| Demo surface | **Offline benchmark + static chart asset** | reliable during the pitch; no live-GPU dependency mid-presentation |
| Comparison method | **Same wall-clock budget**, compare solve time + solution quality | the only fair, honest comparison |
| Matrix vs solve timing | **Measured and reported separately** | the road-graph all-pairs Dijkstra is Python work; isolating it keeps the *solver* comparison clean |

## 4. Architecture

```
make_scale_world(n_customers, n_vehicles, seed)  ──▶  WorldState (real road graph)
                                                          │
                                   build_routing_problem (existing, unchanged)
                                          │  (matrix build — parallelized, timed separately)
                                          ▼
                                   RoutingProblem  ──┬──▶ CpuSolver   (same time budget)
                                                     └──▶ CuOptAdapter (same time budget, H200)
                                                          │
                                          metrics: solve_time, served/dropped, cost, feasible
                                                          ▼
                                          scale_benchmark.py  ──▶  CSV + matplotlib chart
```

### 4.1 Scale generator — `fleet/routing/scale_gen.py` (pure, deterministic, no GPU)
`make_scale_world(n_customers, n_vehicles, seed) -> WorldState` building a **realistic** world
from the existing `fleet.contracts.state` dataclasses:
- **Geography:** seeded random lat/lng for depot + N customers in a bounded region.
- **Road graph:** a sparse directed graph — connect each node to its *k* nearest neighbours
  (both directions), `RoadEdge.effective_time` from haversine distance ÷ speed. Inject a small
  fraction of `FLOODED`/`BLOCKED` edges and a few parallel (multi-edge) routes so the graph
  exercises the same passability/`wade_capability` logic the real demo uses.
- **Fleet:** `n_vehicles` of mixed `veh_type` (varied capacity + `wade_capability`), shifts
  from depot hours.
- **Demand:** seeded per-customer orders, time windows, priorities spanning 1–4.
- Returns a `WorldState` that drops straight into the **unchanged** `build_routing_problem`.

### 4.2 Matrix build at scale (the honest caveat, handled)
`build_time_matrix` runs Dijkstra from each location, so cost grows ~O(N²·k·log N). This is
**graph work, not solver work** — so the benchmark:
- **times it separately** from the solve, and
- **parallelizes it across the 192 CPU cores** (a `multiprocessing` map over source nodes;
  `shortest_times_from` is already independent per source). A genuine use of the box's CPU.
- caps the sweep at the largest N where matrix build stays tolerable, and reports that ceiling.

### 4.3 Benchmark harness — `scripts/scale_benchmark.py` (offline)
- Sweep sizes, e.g. `[50, 100, 250, 500, 1000, 2000, …]` (configurable), fixed vehicle:customer
  ratio.
- For each N: build the world + matrix once (timed), then solve with **both**:
  - `CpuSolver` with `settings.solver_time_limit_sec = BUDGET` (GLS metaheuristic).
  - `CuOptAdapter` against the **real cuOpt server on the H200**, same time budget.
- Record per (N, solver): `matrix_build_s`, `solve_s`, `feasible`, `served`, `dropped`,
  `solution_cost`.
- Emit `scale_results.csv` and a matplotlib figure (solve time vs N, and solution cost vs N,
  log-scale x) saved under a demo-assets dir.

### 4.4 Serving cuOpt
Deploy the self-hosted cuOpt container on a GPU subset (per the Guide's NIM/Docker pattern);
point `settings.cuopt_endpoint` at it. `CuOptAdapter`'s existing lazy transport handles the
rest. The benchmark is the only thing that needs the live server.

## 5. Components & boundaries

| Unit | Purpose | Deps | Runtime? |
|---|---|---|---|
| `fleet/routing/scale_gen.py` | params → realistic large `WorldState` | state dataclasses only | pure (testable) |
| `scripts/scale_benchmark.py` | sweep, dual-solve, CSV + chart | scale_gen, build_routing_problem, both solvers, cuOpt server | offline |

No changes to the loop, UI, `CpuSolver`, `CuOptAdapter`, `matrix.py`, or `build_routing_problem`
— this spec is **purely additive**. The test suite never needs a GPU (cuOpt transport injected;
scale_gen is pure).

## 6. Evaluation / what the chart must show
- **Solve time vs N**, same budget: the crossover where OR-Tools can no longer return a good
  solution within budget while cuOpt stays fast.
- **Solution quality vs N**: served/dropped and cost — at large N, OR-Tools within budget drops
  more tasks / costs more; cuOpt holds quality.
- **One headline number** for the pitch (e.g. "at N=2000, cuOpt solved in X s vs OR-Tools
  Y× slower / Z% worse within the same N-second budget"). Pull the exact numbers from the run;
  don't pre-write them.

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Matrix build dominates wall-clock and muddies the story | time it separately; parallelize across 192 cores; cap N |
| OR-Tools surprisingly competitive at the chosen sizes | push N higher and/or tighten the time budget until the gap is clear; report honestly wherever the crossover actually is |
| cuOpt request payload large at high N (N² matrix) | expected; cuOpt handles it — note payload size in results |
| Generated graph unrealistic | k-nearest + flood/blocked/parallel edges mirror the demo world's structure; sanity-check a small N visually |

## 8. Definition of done (milestones, independently demoable)

1. **M-A:** `scale_gen.py` produces a valid large `WorldState` that passes `build_routing_problem`
   and solves end-to-end with `CpuSolver` (no GPU needed). Unit-tested, deterministic.
2. **M-B:** parallel matrix build wired + timed separately; sweep runs CPU-only across the size
   range and writes CSV.
3. **M-C:** cuOpt server deployed on H200; harness runs both solvers under the same budget; chart
   asset generated with real numbers + the headline figure for the pitch.

Each milestone = its own plan in the plan-series, executed in a separate session.
