# Sovereign Brain — self-hosted, domain-tuned decision LLM

> Version: 1.1 · Date: 2026-06-05 · (1.1: teacher = Sonnet 4.6 + Batch, dataset 1–3k, cost analysis)
> Status: design approved, awaiting spec review
> Scope: ONE of three competition-upgrade specs (the others: cuOpt-at-scale, demo-polish).
> Context: NVIDIA Open Hackathon 2026 (Viettel × NVIDIA). Team server = 8× H200,
> ~1.1 TB GPU mem, ~2 TB RAM, 192 cores, ~28 TB NVMe. Judging weights: NVIDIA-stack
> usage, business impact/demo, and technical novelty (all three).

---

## 0. One sentence

Replace the third-party Claude API decision engine with a **supply-chain decision model
the team owns** — fine-tuned (LoRA) from the simulator's own decision traces and served
entirely on the team's H200s via a self-hosted NVIDIA NIM — slotted behind the existing
`DecisionEngine` interface with a fallback chain that makes the demo impossible to hard-fail.

## 1. Why this is the flagship

- **NVIDIA stack:** exercises NIM (self-hosted inference) + the H200s for both LoRA
  fine-tuning and serving. cuOpt is already integrated; this completes the "runs on NVIDIA
  hardware, no external dependency" story.
- **Business:** data sovereignty (supply-chain data never leaves the customer's infra),
  zero per-call API cost, works air-gapped/offline, and typically **lower decision latency**
  than a remote API round-trip.
- **Novelty:** a real teacher→student **distillation** pipeline, where the team's own
  simulator is the data source — no external dataset needed.

## 2. Non-goals

- NOT training a foundation model from scratch.
- NOT changing the loop, approval gate, dispatcher, or `Decision`/`Event` schema.
- NOT removing Claude — Claude becomes the offline *teacher* (label generator), not a
  runtime dependency.
- NOT multi-turn / tool-using agents — keep the existing one-call-per-event, single-turn,
  structured-output shape so train-time and serve-time prompts are byte-identical.

## 3. Decisions locked

| Decision | Choice | Why |
|---|---|---|
| Base model | **Llama-3.1-Nemotron-Nano-8B** | exact NIM in the Guide; 8B ample for structured decisions; fast to tune+serve; NVIDIA-branded |
| Training stack | **HF PEFT/TRL LoRA → serve via NIM multi-LoRA** | low-risk, well-trodden; LoRA adapter loads into NIM so serving stays on the NVIDIA stack |
| Teacher | Claude **Sonnet 4.6**, thinking **disabled**, via **Batch API** | near-Opus quality on this 7-way+reasoning task at a fraction of the cost; thinking off because we train on the JSON `reasoning` field, not omitted thinking content; emits the exact `(action, reasoning, added_delay_min)` schema (same as `ClaudeAgent`) |
| Free fallback labeler | `RuleBasedEngine` (deterministic event→action) | $0 backup + coverage for rare event types the teacher sees too seldom |
| Integration | new `NimAgent` reusing pure `build_messages`/`parse_decision`, transport injected | mirrors the established Claude/cuOpt injected-transport pattern |

## 4. Architecture — 5 stages

```
simulator scenarios ──▶ ClaudeAgent (teacher) ──▶ JSONL dataset
        (gen)                 (label)                   │
                                                        ▼
                                              PEFT/TRL LoRA fine-tune (H200)
                                                        │
                                                        ▼
                          NIM (base Nemotron-Nano-8B + LoRA adapter, guided-JSON)
                                                        │
                                                        ▼
                          NimAgent (DecisionEngine impl) ──▶ existing loop / approval
```

### 4.1 Data factory — `scripts/gen_dataset.py` (offline, not in runtime path)
- Drive `WorldSimulator` over **N seeded scenarios**. **Start at ~1,000 labeled examples;
  scale to ~3,000 only if §6 eval demands it** — LoRA on this narrow 7-way+reasoning task
  converges with little data, so generate-evaluate-then-grow rather than over-producing.
  Span all 4 disruption classes (supply / demand / transport / retail) and all
  `EventSeverity` levels. Vary seeds, fleet size, pending load, and injected
  `disrupt_edge` states for diversity.
- For each `(state, event)`: call the **Sonnet 4.6 teacher (thinking off) via the Batch API**
  → `(action, reasoning, added_delay_min)`. The teacher transport is its own thin function
  (not the runtime `ClaudeAgent`, which is Opus+adaptive); it reuses the same structured-output
  schema. Batch is ideal here: data-gen is not latency-sensitive.
- Backfill **rare event types** that the teacher sees too seldom using `RuleBasedEngine` so every
  `DecisionAction`/event combination has coverage. (`RuleBasedEngine` is also the **$0 fallback
  labeler** if the team decides to spend nothing — at the cost of reasoning quality/generalization.)
- Reuse `build_messages(state, event)` **verbatim** for the prompt fields → train/serve parity.
- Output JSONL records: `{"system":…, "user":…, "assistant": {decision JSON}}`.
- **Held-out split by scenario seed** (not by row) so no scenario leaks across train/test.

### 4.1a Cost (data generation)
Per label ≈ 200 input + ~100 output tokens (no thinking). At Sonnet 4.6 ($3/$15 per 1M)
via Batch API (−50%): **~$1 for 1k labels, ~$3 for 3k**. Worst case (Opus 4.8, no batch,
3k) is ~$10. Confirm exact token counts with `messages.count_tokens` on a real prompt
before the run. The "data is too expensive to generate" concern does not apply — the
prompts are tiny. $0 is also achievable via the rule-engine / templated-reasoning fallback.

### 4.2 Dataset format
Instruction-tuning chat format matching the model's template. Assistant turn = the strict
`_DECISION_SCHEMA` JSON object (`action` ∈ the 7 `DecisionAction` values, `reasoning`,
`added_delay_min`). Persist under `/raid/team/datasets/sovereign-brain/` (survives restart).

### 4.3 Fine-tune — `scripts/train_lora.py`
- HF Transformers + TRL `SFTTrainer` + PEFT LoRA on the base model.
- Multi-GPU via `accelerate`/FSDP across the H200s; target hours, not days.
- Checkpoints + adapter to `/raid/team/adapters/sovereign-brain/`.
- Log train/val loss; keep the run reproducible (seed, config committed).

### 4.4 Serve — self-hosted NIM
- `docker run` the Nemotron-Nano-8B NIM (per Guide §"Deploy NIM") on a GPU subset
  (e.g. `--gpus '"device=0,1"'`), cache under `/raid/nim-cache`.
- Load the LoRA adapter (NIM multi-LoRA), expose the OpenAI-compatible endpoint on a port.
- **Guided-JSON decoding** constrained to `_DECISION_SCHEMA` so output is always a valid
  `Decision` (belt-and-suspenders on top of the fine-tune).

### 4.5 Integrate — `fleet/agent/nim_agent.py`
- New `NimAgent(settings, complete=None)` implementing `DecisionEngine`.
- **Reuse the pure functions** `build_messages` and `parse_decision` from `claude_agent`
  (or lift them to a shared `fleet/agent/_prompt.py` if cleaner) — only the transport differs.
- `complete(system, user) -> dict` injected for offline tests; lazy default builds an
  OpenAI-compatible client pointed at `settings.nim_endpoint` (optional `openai` dep,
  imported lazily, never touched by the test suite).
- Add enum value `DecisionEngine.LOCAL_NIM = "local_nim"`; `parse_decision` is parameterized
  to stamp the engine (default keeps Claude's behavior; `NimAgent` passes `LOCAL_NIM`).

### 4.6 Config / factory
- `settings.py`: add `decision_engine` value `"nim"`, `nim_endpoint: str = ""`,
  `nim_model: str = "nvidia/llama-3.1-nemotron-nano-8b-v1"`.
- `factory.build_components`: select `NimAgent` when `decision_engine == "nim"` AND
  `nim_endpoint` set; else existing Claude/rule logic. One-line change, mirrors cuOpt.

## 5. Fallback chain (demo-safety, non-negotiable)

`fine-tuned NIM` → (invalid output / endpoint down) → `base NIM` → (down) → `rule-based`.
`NimAgent.decide` keeps the existing per-event try/except → rule fallback (same as
`ClaudeAgent._fallback`, tagged `engine=RULE_BASED`). Even worst case, the "no third-party
API, runs on our hardware" story holds.

## 6. Evaluation — `scripts/eval_brain.py`

- **Offline (vs held-out):** action-agreement % vs Claude teacher; JSON-validity rate;
  per-event-type confusion.
- **Online (full simulator run):** `NimAgent` vs `ClaudeAgent` vs `RuleBasedEngine` on
  on-time % , total cost/delay, and **decision latency** (local NIM vs Claude API round-trip).
- Produce a small report (table + the latency win) for the demo/pitch.

## 7. Components & boundaries

| Unit | Purpose | Depends on | Runtime? |
|---|---|---|---|
| `scripts/gen_dataset.py` | scenarios → labeled JSONL | simulator, Sonnet-4.6 Batch teacher, rule engine | offline |
| `scripts/train_lora.py` | JSONL → LoRA adapter | HF/TRL/PEFT, H200 | offline |
| `scripts/eval_brain.py` | metrics + report | simulator, agents | offline |
| `fleet/agent/nim_agent.py` | `DecisionEngine` over NIM | pure prompt fns, injected transport | **runtime** |
| `factory.py` + `settings.py` | select NimAgent by config | — | runtime |

Only `nim_agent.py` + config touch the runtime path; the test suite never imports `openai`,
never hits the network, never needs a GPU (transport injected) — same discipline as
`ClaudeAgent`/`CuOptAdapter`.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Fine-tune underperforms teacher | base-NIM fallback keeps the self-hosted story; report agreement honestly |
| Data too uniform (teacher picks same action) | rule-engine backfill + seed/scenario diversity; report per-event-type coverage |
| Labeling cost / no budget | Sonnet 4.6 + Batch keeps 1–3k labels at ~$1–3; rule-engine/templated-reasoning path is $0 |
| NIM LoRA serving setup eats the clock | base NIM (no adapter) is a valid milestone; LoRA is the stretch within the flagship |
| Time pressure | stages are independently shippable: NIM-serve → NimAgent → dataset → fine-tune → eval |

## 9. Definition of done (milestones, independently demoable)

1. **M-A:** base Nemotron-Nano-8B NIM serving locally; `NimAgent` wired via factory;
   full simulator loop runs end-to-end on the self-hosted model (no Claude, no API key).
2. **M-B:** dataset generated + committed (with held-out split); counts/coverage reported.
3. **M-C:** LoRA fine-tuned; adapter served via NIM; eval report (agreement, validity, latency).
4. **M-D:** `eval_brain.py` online comparison (NIM vs Claude vs rule) wired into the demo.

Each milestone = its own plan in the plan-series, executed in a separate session.
