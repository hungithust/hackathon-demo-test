# Sovereign Brain v2 — outcome-verified self-hosted decision LLM

> Version: 2.0 · Date: 2026-06-07
> Status: design approved, awaiting spec review
> Supersedes the training-signal of v1.1 (`2026-06-05-sovereign-brain-design.md`):
> v1.1 = pure imitation of the Claude teacher; v2 adds a **simulator-as-oracle**
> outcome-verification stage so the student learns decisions the world *proved* good,
> not just decisions the teacher *guessed*. v1.1's serving/NIM/fallback design is kept.
> Context: NVIDIA Open Hackathon 2026 (Viettel × NVIDIA). Team server = 8× H200
> (full access, usable now), ~1.1 TB GPU mem, ~2 TB RAM, 192 cores, ~28 TB NVMe.
> Judging weights: NVIDIA-stack usage, business impact/demo, technical novelty.

---

## 0. One sentence

Replace the third-party Claude API decision engine with a supply-chain decision model the
team owns — fine-tuned (LoRA) from **outcome-verified** decision traces (the team's own
simulator rolls every candidate action forward and grades the realized cost) and served
entirely on the team's H200s via a self-hosted NVIDIA NIM — slotted behind the existing
`DecisionEngine` interface with a fallback chain that makes the demo impossible to hard-fail.

## 1. Why this is the flagship (and why v2 over v1.1)

- **NVIDIA stack (the heaviest judging axis):** exercises NIM (self-hosted inference) + the
  H200s for both LoRA fine-tuning and serving. cuOpt is already integrated; this completes
  the "runs on NVIDIA hardware, no external dependency" story.
- **Business:** data sovereignty (supply-chain data never leaves the customer's infra),
  zero per-call API cost, works air-gapped/offline, and typically **lower decision latency**
  than a remote API round-trip.
- **Novelty (the v2 weight):** v1.1 imitates Claude and is therefore capped at the teacher's
  quality. v2 makes the **simulator an oracle** — every candidate action is applied to a clone
  of the world, rolled forward, and graded by realized cost. The student learns
  outcome-verified decisions and can therefore **beat the teacher** on on-time %. The pitch:
  *"We don't copy Claude — the world-model grades every decision; the brain learns only what's
  proven."* This also fixes a real weakness in the shipped `ScoringEngine` (M-D), whose
  `_ACTION_EFFECT` table is a hardcoded delay/drop heuristic — the oracle replaces that guess
  with measured simulator outcome.

## 2. Non-goals

- NOT training a foundation model from scratch.
- NOT changing the loop, approval gate, dispatcher, or `Decision`/`Event` schema.
- NOT removing Claude — Claude becomes the offline *reasoning labeler* (justifying the
  oracle-chosen action), not a runtime dependency.
- NOT multi-turn / tool-using agents — keep the existing one-call-per-event, single-turn,
  structured-output shape so train-time and serve-time prompts are byte-identical.
- NOT changing how the oracle's cost weights are defined — reuse `ScoringEngine`'s
  `score_w_sla / score_w_delay / score_w_drop` so cost stays in one unit across the codebase.

## 3. Decisions locked

| Decision | Choice | Why |
|---|---|---|
| Base model | **Llama-3.1-Nemotron-Nano-8B** | exact NIM in the Guide; 8B ample for structured decisions; fits 1–2 H200s; NVIDIA-branded |
| Training stack | **HF PEFT/TRL LoRA → serve via NIM multi-LoRA** | low-risk, well-trodden; adapter loads into NIM so serving stays on the NVIDIA stack |
| Training signal | **Outcome-verified SFT (rejection sampling)** core; **DPO** stretch | the simulator grades realized cost; student learns proven-good labels, not teacher guesses |
| Oracle grader | clone world → `dispatcher.apply` → `simulator.tick × horizon` → realized cost | reuses shipped machinery; deterministic; CPU-only; testable without GPU |
| Reasoning labels | Claude **Sonnet 4.6**, thinking off, **Batch API**, *conditioned on the oracle action* | natural-language reasoning the judges read, without letting the teacher override the verified action; `$0` templated fallback exists |
| Free fallback labeler | `RuleBasedEngine` (deterministic event→action) | `$0` backup + coverage for rare event types |
| Integration | new `NimAgent` reusing pure `build_messages`/`parse_decision`, transport injected | mirrors the established Claude/cuOpt injected-transport pattern |

## 4. Architecture — 8 stages

```
[OFFLINE — data generation + training, never in the runtime path]

1. Scenario gen   WorldSimulator × N seeds → (state, event) spanning 4 disruption classes + all severities
        │
2. Candidates     candidate_actions(event)  (+ optional teacher proposals)
        │
3. ORACLE  ◀── the v2 novelty
   per candidate: deepcopy((simulator, state)) → dispatcher.apply → tick × horizon → realized_cost
   → verified-best action  (DPO: also keep best/worst pair)
        │
4. Label assembly reasoning from Sonnet Batch (conditioned) OR templated $0; prompt = build_messages → JSONL
        │
5. Fine-tune      PEFT/TRL LoRA on Nemotron-Nano-8B, H200 (accelerate/FSDP)
        │
6. Serve          NIM Docker + LoRA adapter, OpenAI-compatible endpoint, guided-JSON

[RUNTIME — only this part touches production]

7. NimAgent (DecisionEngine) ──decide()──▶ existing loop / approval (schema unchanged)
8. Eval           offline (agreement vs oracle ground-truth, validity) + online (NIM vs Claude vs rule vs scoring)
```

### 4.1 Scenario generation — inside `scripts/gen_dataset.py` (offline)
Drive `WorldSimulator` over **N seeded scenarios**, one timeline per seed. Collect
`(state, event)` pairs spanning **all 4 disruption classes** (supply / demand / transport /
retail) and **all `EventSeverity`** levels. Vary seeds, fleet size, pending load, injected
`disrupt_edge` states for diversity. **Start at ~1,000 examples; scale to ~3,000 only if §6
eval demands it.**

### 4.2 Oracle — `fleet/agent/oracle.py` (pure, CPU, testable)
For each `(state, event)` and each candidate action:

```python
branch = deepcopy((simulator, state))      # clone the rng too → identical future across branches
branch.dispatcher.apply(branch.state, Decision(action=candidate, ...))
for _ in range(settings.oracle_horizon_ticks):
    branch.simulator.tick(branch.state)
cost = realized_cost(branch.state, settings)   # the world's ACTUAL outcome
```

- `realized_cost(state, settings)` reads what actually happened in the clone — real total
  delay, real **late/dropped** orders, priority-weighted — **not** the `_ACTION_EFFECT` table.
  It reuses `ScoringEngine`'s weights (`score_w_sla / score_w_delay / score_w_drop`) so cost
  is in one unit.
- **Fairness pillar (anti reward-noise):** every candidate rolls forward from the *same clone
  with the same RNG state*, so the future (demand / weather) is **identical** across branches —
  the only difference is the action. This is why the **simulator** must be cloned (the seeded
  `self.rng` / `self._weather_rng` live on it), not just the `WorldState`.
- Verified label = the action with the lowest realized cost; deterministic tie-break by
  `action.value`. DPO (stretch) additionally keeps the **best (chosen) / worst (rejected)**
  pair.

### 4.3 Anti reward-hacking (traps handled)
- **Horizon too short** (effect not yet realized) → `oracle_horizon_ticks` configurable, set
  long enough for action effects to materialize.
- **All candidates tie** (no learnable signal) → if the best/worst cost gap is below
  `oracle_min_gap`, **drop the example** from training; report the informative-fraction.
- **No proxy to game:** cost is measured on the simulator's real outcome — there is no
  intermediate reward function to exploit.

### 4.4 Label assembly + train/serve parity
- Prompt fields = `build_messages(state, event)` **verbatim** → train/serve byte-identical.
- Assistant turn = strict `_DECISION_SCHEMA` JSON `{action, reasoning, added_delay_min}`:
  `action` = oracle's verified choice; `added_delay_min` = the **measured** roll-forward delay,
  not a hardcoded estimate.
- `reasoning`: **Sonnet 4.6 (thinking off) via Batch API**, prompted to *justify the
  oracle-chosen action* (conditioned — the teacher may not change the action) → good prose
  without label drift. **`$0` path:** templated reasoning from the cost table
  (e.g. "chose REROUTE, simulated cost 12.0 vs reschedule=20.0, defer=60.0").
- Rare event types backfilled with `RuleBasedEngine`.
- Output JSONL `{"system":…, "user":…, "assistant": {decision JSON}}`.
- **Held-out split by scenario seed** (not by row) so no scenario leaks across train/test.
- Persist under `/raid/team/datasets/sovereign-brain/` (survives restart).

### 4.5 Cost (data generation)
- Oracle compute = **CPU, `$0`** (deepcopy + tick only).
- Reasoning labels ≈ 200 input + ~100 output tokens each, Sonnet 4.6 Batch (−50%):
  **~`$1` for 1k, ~`$3` for 3k**. Worst case (Opus 4.8, no batch, 3k) ≈ `$10`.
  **Confirm exact token counts with `messages.count_tokens` on a real prompt before the run.**
  A fully `$0` path exists via templated/rule reasoning.

### 4.6 Fine-tune — `scripts/train_lora.py`
- HF Transformers + TRL `SFTTrainer` + PEFT LoRA on the base model.
- Multi-GPU via `accelerate`/FSDP across the H200s; target **hours, not days**.
- Adapter + checkpoints → `/raid/team/adapters/sovereign-brain/`. Log train/val loss; commit
  seed + config for reproducibility.
- **DPO (stretch):** TRL `DPOTrainer` on the oracle best/worst pairs, initialized from the SFT
  adapter.

### 4.7 Serve — self-hosted NIM
- `docker run` the Nemotron-Nano-8B NIM (Guide §"Deploy NIM") on a GPU subset
  (e.g. `--gpus '"device=0,1"'`), cache under `/raid/nim-cache`.
- Load the LoRA adapter (NIM multi-LoRA); expose the OpenAI-compatible endpoint on a port.
- **Guided-JSON decoding** constrained to `_DECISION_SCHEMA` so output is always a valid
  `Decision` (belt-and-suspenders over the fine-tune).

### 4.8 Integrate — `fleet/agent/nim_agent.py`
- New `NimAgent(settings, complete=None)` implementing `DecisionEngine`.
- **Reuse the pure functions** `build_messages` and `parse_decision` from `claude_agent`
  (or lift them to a shared `fleet/agent/_prompt.py` if cleaner) — only the transport differs.
- `complete(system, user) -> dict` injected for offline tests; lazy default builds an
  OpenAI-compatible client pointed at `settings.nim_endpoint` (optional `openai` dep, imported
  lazily, never touched by the test suite).
- Add enum value `DecisionEngine.LOCAL_NIM = "local_nim"`; `parse_decision` parameterized to
  stamp the engine (default keeps Claude's behavior; `NimAgent` passes `LOCAL_NIM`).

### 4.9 Config / factory
- `settings.py`: add `decision_engine` value `"nim"`, `nim_endpoint: str = ""`,
  `nim_model: str = "nvidia/llama-3.1-nemotron-nano-8b-v1"`, plus oracle knobs
  `oracle_horizon_ticks: int` and `oracle_min_gap: float`.
- `factory.build_components`: select `NimAgent` when `decision_engine == "nim"` AND
  `nim_endpoint` set; else existing Claude/rule/scoring logic. One-line change, mirrors cuOpt.

## 5. Fallback chain (demo-safety, non-negotiable)

`fine-tuned NIM` → (invalid output / endpoint down) → `base NIM` → (down) → `rule-based`.
`NimAgent.decide` keeps the per-event try/except → rule fallback (same as `ClaudeAgent._fallback`,
tagged `engine=RULE_BASED`). Even worst case, the "no third-party API, runs on our hardware"
story holds.

## 6. Evaluation — `scripts/eval_brain.py`

- **Offline (vs held-out):** action-agreement % vs the **oracle ground-truth** (not merely vs
  the teacher); JSON-validity rate; per-event-type confusion.
- **Online (full simulator run):** `NimAgent` vs `ClaudeAgent` vs `RuleBasedEngine` vs
  `ScoringEngine` on on-time %, total cost/delay, and **decision latency** (local NIM vs Claude
  API round-trip).
- **The headline the eval must surface:** because the brain learns oracle-verified outcomes,
  it can **beat the Claude teacher** on on-time %. Measure and report this explicitly.
- Produce a small report (table + the latency win + the beat-the-teacher number) for the pitch;
  pull exact numbers from the run, don't pre-write them.

## 7. Components & boundaries

| Unit | Purpose | Depends on | Runtime? |
|---|---|---|---|
| `fleet/agent/oracle.py` | clone world → apply → tick → realized cost; verified-best label | sim.tick, dispatcher.apply, ScoringEngine weights | **pure / testable, CPU** |
| `scripts/gen_dataset.py` | scenarios → oracle → labeled JSONL (+ Sonnet Batch reasoning) | simulator, oracle, Sonnet Batch, rule engine | offline |
| `scripts/train_lora.py` | JSONL → LoRA adapter (SFT; DPO stretch) | HF/TRL/PEFT, H200 | offline |
| `scripts/eval_brain.py` | metrics + report (offline + online) | simulator, agents | offline |
| `fleet/agent/nim_agent.py` | `DecisionEngine` over NIM | pure prompt fns, injected transport | **runtime** |
| `factory.py` + `settings.py` | select NimAgent by config | — | runtime |

Only `nim_agent.py` + config touch the runtime path. `oracle.py` is pure CPU, tested without
GPU/network (it `deepcopy`s the world and reuses the shipped `dispatcher.apply` + `simulator.tick`).
The test suite never imports `openai`, never hits the network, never needs a GPU — same
discipline as `ClaudeAgent` / `CuOptAdapter`.

## 8. Feasibility validation (the explicit asks)

- **Data:** NO external dataset. Self-generated `(state, event, candidate actions, realized cost)`
  from the deterministic simulator — `$0`, reproducible by seed. Reasoning labels from Sonnet 4.6
  Batch ≈ `$1–3` for 1–3k; **validate real token counts with `messages.count_tokens` first**;
  `$0` templated/rule path exists.
- **Hardware (training):** LoRA (PEFT/TRL) on Nemotron-Nano-8B, multi-GPU H200 via
  accelerate/FSDP. 8B fits comfortably in 1–2 H200s (~140 GB each); training in hours.
- **Hosting:** self-hosted NIM Docker on a GPU subset, OpenAI-compatible endpoint, guided-JSON.
  Test suite never touches GPU/network (transport injected).
- **Must verify early (in M-A planning):** `WorldState` + `WorldSimulator` `deepcopy` cleanly and
  `apply + tick` leak no side effects outside the clone — this is the oracle's load-bearing
  assumption.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `deepcopy(simulator, state)` leaks state or is too slow | verify in M-A first; if a field can't be deep-copied, add a `clone()`; cache the clone per `(state,event)` and reuse across candidates |
| Oracle horizon too short → wrong labels | `oracle_horizon_ticks` tunable; sanity-check a few labels by hand in M-A |
| All candidates tie → no signal | drop examples below `oracle_min_gap`; report informative-fraction |
| Fine-tune underperforms | base-NIM fallback keeps the self-hosted story; report agreement honestly |
| Data too uniform | rule-engine backfill + seed/scenario diversity; report per-event-type coverage |
| Labeling cost / no budget | Sonnet 4.6 + Batch keeps 1–3k labels at ~`$1–3`; templated/rule path is `$0` |
| NIM LoRA serving eats the clock | base NIM (no adapter) is a valid milestone (M-C); LoRA is M-D |
| Time pressure | stages independently shippable: oracle → data → serve → fine-tune → DPO |

## 10. Definition of done (milestones — each its own plan, separate session, independently demoable)

1. **M-A — Oracle:** `oracle.py` + `realized_cost`, deterministic CPU tests (clone → apply →
   tick → cost; verify deepcopy cleanliness + identical-future fairness). No GPU.
2. **M-B — Data factory:** `gen_dataset.py` emits oracle-verified JSONL (+ Sonnet Batch
   reasoning, `$0` fallback), held-out split by seed, reports coverage + informative-fraction.
3. **M-C — Serve + integrate:** base NIM serving + `NimAgent` wired via factory + fallback
   chain; full loop runs end-to-end on the self-hosted model (no Claude, no API key).
4. **M-D — Fine-tune + eval:** LoRA fine-tuned on H200, adapter served via NIM, `eval_brain.py`
   offline + online with the headline numbers (latency win + beat-the-teacher).
5. **M-E — DPO (stretch):** preference pairs from the oracle → `DPOTrainer` → re-eval.

**Dependency order:** M-A → M-B (needs oracle) → M-D (needs M-B data). M-C is independent
(only needs base NIM) and can run in parallel. M-E last.
