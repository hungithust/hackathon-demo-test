# Voice Disruption Intake — Design Spec

**Date:** 2026-06-08
**Status:** Approved-pending-review (brainstormed 2026-06-08)
**Branch:** `feat/base-project`
**Spec type:** Hackathon hero-feature (1 spec → 1 plan → execute in separate session)

## 1. Overview

A **field-report sensor layer** (`fleet/intake/`) that lets the supply-chain
dispatcher report a real-world disruption **by voice or free text** directly in
the control tower. Speech → text (ASR) → an LLM extractor turns it into one or
more structured `IntakeReport`s → the report is injected into the live world via
the **existing** `WorldSimulator.inject_event` / `disrupt_edge` seam → the
existing detect → decide → reroute pipeline fires on screen, surfacing the
agent's decision and reasoning.

This is the hackathon **hero-feature**: in one spoken sentence it exercises
**three NVIDIA components** (Riva/Whisper ASR → Nemotron NIM extractor →
cuOpt reroute) and closes the problem statement's step ① *"tiếp nhận dữ liệu từ
hiện trường"* without a mobile app — the dispatcher (the primary user) is the
one reporting.

**Scope decision (2026-06-08):** image input is **dropped** for safety; this
spec is **voice + text only**. Vision/photo triage is a documented future
stretch (§11), not built here.

## 2. Goals / Non-goals

**Goals**
- Voice or text disruption report → valid `Event` injected into the running sim.
- Reuse the existing transport pattern (injected `complete(system,user)->dict`)
  so the extractor runs on the **already-deployed Nemotron NIM** — no new NGC
  entitlement required for the core path.
- ASR behind a swappable interface: Riva NIM (premium) **or** self-hosted
  Whisper (Vietnamese-strong fallback) **or** off (text-only).
- Every new unit is **offline-testable** with injected transports (no GPU, no
  API key, no entitlement) — matching `ClaudeAgent`/`NimAgent`/`CuOptAdapter`.
- Default path unchanged: intake disabled by default → the existing 255-test
  suite stays green.
- A Streamlit "Báo cáo sự cố" panel that accepts **mic, file upload, and text**
  (so the demo works regardless of whether the demo machine has a microphone).

**Non-goals (YAGNI)**
- No native mobile app, no two-way dispatch-push to the field, no GPS telemetry,
  no real map tiles, no TTS read-back, no image/photo input (this spec).

## 3. Architecture

```
audio bytes ──▶ Transcriber.transcribe() ──▶ raw_text ─┐
                                                        │
text box ──────────────────────────────────────────────▶ extract_event(text, state)
                                                                         │  (LLM, JSON schema)
                                                                         ▼
                                                              list[IntakeReport]
                                                                         │ resolve_target(state)
                                                                         ▼
                                          edge event ─▶ sim.disrupt_edge(edge_id, status, ...)
                                          else ───────▶ sim.inject_event(type, target, severity)
                                                                         │
                                                                 controller.step(1)
                                                                         ▼
                                            existing detect → decide → reroute → decision card
```

Three layers, each a focused unit behind a clear interface:

1. **Sensors** (`Transcriber`) — bytes → text. Swappable impls, injected transport.
2. **Understanding** (pure `extract_event` + `resolve_target`) — text → structured
   `IntakeReport` with a concrete world target. Pure, deterministic, no I/O.
3. **Orchestration** (`IntakeController`) — wires sensor → understanding →
   `inject_event`/`disrupt_edge` → `SimulationController.step`.

`fleet/contracts/` still imports nothing. The new package depends only on
contracts + simulator + the existing agent transport helpers.

## 4. Components

### 4.1 `fleet/intake/report.py` (pure data)
```python
@dataclass(frozen=True)
class IntakeReport:
    event_type: EventType            # one of the 6 existing enum values
    target: str                      # resolved id: customer_id | vehicle_id | edge_id
    severity: EventSeverity          # low|medium|high|critical
    raw_text: str                    # transcript / typed text the report came from
    confidence: float = 1.0          # extractor self-rated 0..1 (for UI sorting)
    # edge-only hints (ignored for non-edge events):
    edge_status: EdgeStatus | None = None     # flooded|blocked|congested
    flood_level: float = 0.0
    traffic_factor: float = 1.0
```

### 4.2 `fleet/intake/extractor.py` (pure)
- `build_intake_messages(text: str, state: WorldState) -> tuple[system, user]`
  — system prompt defines the 6 `EventType`s and 4 `EventSeverity`s; user prompt
  embeds the report text plus a compact roster of the world (customer ids+names,
  vehicle ids, edge ids+endpoints) so the model can name a real target.
- `_INTAKE_SCHEMA` — strict `json_schema`: `{reports: [{event_type(enum),
  target_hint(str), severity(enum), confidence(number), edge_status(enum|null),
  flood_level(number), traffic_factor(number)}]}`. A single utterance can yield
  **multiple** reports (e.g. "ngập + xe hỏng").
- `parse_intake(data, state) -> list[IntakeReport]` — validates enums (raises
  `ValueError` on bad action, like `parse_decision`), resolves `target_hint` via
  `resolve_target`, drops reports whose target cannot be resolved.

### 4.3 `fleet/intake/resolver.py` (pure)
- `resolve_target(hint: str, event_type: EventType, state) -> str | None`
  — deterministic fuzzy match of a free-text mention to a concrete id:
  - vehicle events → match against `state.vehicles` ids / "xe 3" → `V3`.
  - edge events (`traffic`, `flooded_area`) → match against `road_graph` edges by
    endpoint customer name/id → returns `edge_id`.
  - customer/demand/inventory/urgent events → match against `state.customers`
    by id, name, or address substring → returns `customer_id`.
  - Normalizes Vietnamese (casefold, strip accents) for robust matching. Returns
    `None` if nothing matches (report is dropped, surfaced to UI as "unresolved").

### 4.4 `fleet/intake/asr.py` (interface + impls)
- `class Transcriber(Protocol): def transcribe(self, audio: bytes, lang: str) -> str: ...`
- `WhisperTranscriber(transcribe_fn=None)` — injected callable for tests; lazy
  default loads a self-hosted Whisper (HF `transformers` / faster-whisper) on
  GPU. Vietnamese-capable. **No NGC entitlement needed.**
- `RivaTranscriber(transcribe_fn=None)` — injected callable for tests; lazy
  default calls a Riva ASR NIM endpoint (premium, "pure NVIDIA").
- `NullTranscriber` — raises if called; selected when `ASR_ENGINE=none`
  (text-only mode). Tests never import torch/whisper/riva.

### 4.5 `fleet/intake/controller.py`
- `class IntakeController` wrapping a `SimulationController`:
  - `report(text: str | None = None, audio: bytes | None = None,
    lang: str = "vi") -> IntakeResult` — if `audio`, transcribe first; run
    `extract_event` (via injected `complete` transport, default = the same NIM
    transport the decision engine uses); for each `IntakeReport` call
    `disrupt_edge` (edge events) or `inject_event` (others); then `sim.step(1)`.
  - Returns `IntakeResult{raw_text, reports: list[IntakeReport],
    injected_event_ids, decisions: list[snapshot-shaped]}` for the UI card.
- The extractor `complete` transport defaults to the decision-engine NIM/Claude
  transport from `build_components`, so when `DECISION_ENGINE=nim` the **same
  Nemotron NIM** serves both decisions and intake extraction.

### 4.6 `fleet/ui/app.py` — "Báo cáo sự cố" panel
- A new section in the existing Streamlit app: `st.audio_input` (mic) **+**
  `st.file_uploader` (audio file) **+** `st.text_area` (typed). A "Bóc tách"
  button shows the transcript and the extracted `IntakeReport`s in an editable
  table (operator can correct event_type/target/severity before injecting). An
  "Inject & xử lý" button calls `IntakeController.report`, then re-renders the
  event feed, vehicle map/table, and a **decision card** surfacing the agent's
  `action` + `reasoning` + `engine` (the thin slice of the explainable-copilot
  idea). Streamlit is imported only in `app.py` so tests never import it.

## 5. Config / settings

New `config/settings.py` keys (all default to the no-op / text-only path):
- `ASR_ENGINE = "none"` → `none | whisper | riva`.
- `RIVA_ENDPOINT = ""`, `WHISPER_MODEL = "openai/whisper-large-v3"`.
- `INTAKE_EXTRACTOR = "decision"` → reuse the configured decision-engine
  transport; `"nim"`/`"claude"` to pin explicitly.
- Factory gains `build_transcriber(settings)` selecting the impl; returns
  `NullTranscriber` unless an engine + endpoint/model is configured.

## 6. Data flow & seam correctness

- **Edge events** (`flooded_area`, `traffic`) MUST go through `disrupt_edge`
  (mutates the edge so the routing matrix/reroute actually changes); a bare
  `inject_event` would emit an event the optimizer can't act on. The controller
  picks the path by `event_type`.
- **Node/vehicle events** (`inventory_shortage`, `demand_surge`, `urgent_order`,
  `vehicle_breakdown`) go through `inject_event`.
- After injection the controller calls `step(1)`; the existing loop runs
  detect → decide, queuing a pending `Decision` the operator can approve/reject
  with the existing `approve`/`reject` methods. Reroute happens on approval of a
  `RESOLVE_ACTIONS` decision, exactly as today.

## 7. Error handling & fallbacks

- ASR failure (transport error, model not loaded) → surface a UI error and fall
  back to the text box; never crash the controller.
- Extractor returns invalid/empty JSON → `parse_intake` raises `ValueError`,
  caught by the controller and shown as "không bóc tách được, hãy gõ tay".
- Unresolved target → report dropped with a visible "unresolved: <hint>" note so
  the operator can retype.
- The whole feature degrades gracefully to **text-only on the Nemotron NIM**,
  which is the guaranteed-available path (no extra entitlement, no mic).

## 8. Testing (TDD, offline)

- `test_intake_extractor.py` — `parse_intake` on canned JSON: multi-report split,
  enum validation/`ValueError`, target resolution, edge-vs-node routing hints.
- `test_intake_resolver.py` — vehicle/customer/edge matching incl. accent-folding
  and the `None`/unresolved case.
- `test_intake_asr.py` — `WhisperTranscriber`/`RivaTranscriber` with injected
  `transcribe_fn`; `NullTranscriber` raises; suite imports no torch/whisper/riva.
- `test_intake_controller.py` — injected `complete` + injected transcribe end to
  end: text path and audio path each inject the right event(s) via
  `disrupt_edge`/`inject_event` and produce a pending decision; bad JSON handled.
- `test_factory.py` — `build_transcriber` returns `NullTranscriber` by default.
- UI: `app.py` manual smoke only (`streamlit run`), as with M7.

## 9. Time budget (≈10h, AI-coded)

| Work | Est |
|---|---|
| Pure: report, extractor (schema/parse), resolver + tests | 2.0h |
| Transcriber interface + Whisper/Riva/Null impls + tests | 1.5h |
| IntakeController + tests | 1.5h |
| Streamlit panel (mic/upload/text, decision card) | 1.5h |
| Server: deploy Whisper (HF) or pull Riva NIM, live smoke | 1.5h |
| Integration buffer | 1.0h |
| **Total** | **9.0h** |

The pure + text-only path is shippable even if every live-model task slips.

## 10. Open resource items (confirm on node-07 before the live-model tasks)

1. **NGC entitlement** for a Riva ASR NIM — `docker pull` test on node-07. If it
   fails, default ASR to self-hosted Whisper (no entitlement needed).
2. **HF access** to `openai/whisper-large-v3` (ungated) on the box, or a
   `/raid` cache — verify download.
3. **Demo channel** — confirm a web port can be exposed on node-07 during
   judging (Guide allows it) and whether the demo browser has a mic; the panel
   supports file-upload + text regardless, so this is non-blocking.

## 11. Future stretch (not this spec)

- **Image/photo triage** — `IncidentVision` interface + a Vision NIM / self-host
  VLM classifying flood/accident photos into `(event_type, severity)`. Dropped
  here for safety; the controller's report path is already shaped to accept an
  extra modality later.
- Two-way dispatch-push back to field staff; Riva **TTS** read-back of the agent
  decision.
