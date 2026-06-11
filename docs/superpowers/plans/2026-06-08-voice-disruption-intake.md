# Voice Disruption Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `fleet/intake/` sensor layer that turns a spoken or typed disruption report into a structured `Event` injected into the live simulation, so the existing detect→decide→reroute pipeline reacts on screen.

**Architecture:** Three focused units behind the project's established interface + injected-transport pattern. (1) `Transcriber` (audio→text, swappable Whisper/Riva/Null). (2) pure `extract_event` + `resolve_target` (text→structured `IntakeReport` with a concrete world target). (3) `IntakeController` orchestrating sensor→understanding→`inject_event`/`disrupt_edge`→`SimulationController.step`. Everything is offline-testable with injected transports; the feature is OFF by default so the existing 255-test suite stays green.

**Tech Stack:** Python, existing `fleet.contracts.state` dataclasses, `fleet.ui.controller.SimulationController`, `fleet.simulator.engine.WorldSimulator` (`inject_event`/`disrupt_edge`), an OpenAI-compatible NIM transport (reused pattern from `nim_agent.py`), Streamlit (`st.audio_input`/`st.file_uploader`) for the panel. Optional live deps (`openai`, `faster-whisper`/`transformers`) are lazy-imported only.

Spec: `docs/superpowers/specs/2026-06-08-voice-disruption-intake-design.md`.

---

## File Structure

- Create `fleet/intake/__init__.py` — package marker.
- Create `fleet/intake/report.py` — `IntakeReport`, `IntakeResult` dataclasses (pure data).
- Create `fleet/intake/resolver.py` — `resolve_target(hint, event_type, state)` (pure).
- Create `fleet/intake/extractor.py` — `_INTAKE_SCHEMA`, `build_intake_messages`, `parse_intake` (pure).
- Create `fleet/intake/asr.py` — `Transcriber` protocol + `WhisperTranscriber`/`RivaTranscriber`/`NullTranscriber`.
- Create `fleet/intake/controller.py` — `IntakeController` + lazy `build_intake_complete`.
- Modify `config/settings.py` — 4 new settings + env parsing.
- Modify `fleet/factory.py` — `build_transcriber(settings)`.
- Modify `fleet/ui/app.py` — "Báo cáo sự cố" panel (manual smoke only).
- Modify `requirements.txt` — optional-dep comments.
- Create tests: `tests/test_intake_resolver.py`, `tests/test_intake_extractor.py`, `tests/test_intake_asr.py`, `tests/test_intake_controller.py`; extend `tests/test_factory.py`.

---

## Task 1: Package skeleton + data records

**Files:**
- Create: `fleet/intake/__init__.py`
- Create: `fleet/intake/report.py`
- Test: `tests/test_intake_controller.py` (temporary import smoke; replaced in Task 5)

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_controller.py`:

```python
from fleet.intake.report import IntakeReport, IntakeResult
from fleet.contracts.state import EventType, EventSeverity, EdgeStatus


def test_intake_report_defaults():
    r = IntakeReport(event_type=EventType.INVENTORY_SHORTAGE, target="C001",
                     severity=EventSeverity.HIGH, raw_text="kho C001 het hang")
    assert r.confidence == 1.0
    assert r.edge_status is None
    assert r.flood_level == 0.0
    assert r.traffic_factor == 1.0


def test_intake_result_holds_reports():
    res = IntakeResult(raw_text="x", reports=[], injected_event_ids=[], decisions=[])
    assert res.reports == [] and res.injected_event_ids == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_controller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.intake'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/intake/__init__.py`:

```python
"""Field-report sensor layer: voice/text disruption reports -> structured Events
injected into the live world via the existing inject_event/disrupt_edge seam."""
```

Create `fleet/intake/report.py`:

```python
"""Pure data records for the intake layer."""

from dataclasses import dataclass, field
from typing import List, Optional

from fleet.contracts.state import EventType, EventSeverity, EdgeStatus


@dataclass(frozen=True)
class IntakeReport:
    event_type: EventType
    target: str                       # resolved id: customer_id | vehicle_id | edge_id
    severity: EventSeverity
    raw_text: str                     # transcript / typed text this came from
    confidence: float = 1.0
    edge_status: Optional[EdgeStatus] = None   # edge events only
    flood_level: float = 0.0
    traffic_factor: float = 1.0


@dataclass
class IntakeResult:
    raw_text: str
    reports: List[IntakeReport] = field(default_factory=list)
    injected_event_ids: List[str] = field(default_factory=list)
    decisions: List[dict] = field(default_factory=list)   # snapshot-shaped pending decisions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_intake_controller.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add fleet/intake/__init__.py fleet/intake/report.py tests/test_intake_controller.py
git commit -m "feat(intake): package skeleton + IntakeReport/IntakeResult records"
```

---

## Task 2: Target resolver (pure)

Maps a free-text mention ("xe 3", "BigC", "C001", "đường vào C001") to a concrete id in the world, with Vietnamese accent-folding. Vehicle events → vehicle id; edge events (traffic/flooded_area) → edge id; everything else → customer id. Returns `None` when nothing matches.

**Files:**
- Create: `fleet/intake/resolver.py`
- Test: `tests/test_intake_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_resolver.py`:

```python
from fleet.intake.resolver import resolve_target
from fleet.scenarios import build_sample_state
from fleet.contracts.state import EventType


def test_resolves_vehicle_by_number():
    state = build_sample_state()
    assert resolve_target("xe 3 bi hong giua duong", EventType.VEHICLE_BREAKDOWN, state) == "V003"


def test_resolves_customer_by_id():
    state = build_sample_state()
    assert resolve_target("kho cua C001 het hang", EventType.INVENTORY_SHORTAGE, state) == "C001"


def test_resolves_customer_by_name_accent_folded():
    state = build_sample_state()
    # "BigC Q.1" is C001's name; report typed without exact case/accents
    assert resolve_target("bigc q.1 can them hang gap", EventType.URGENT_ORDER, state) == "C001"


def test_resolves_flooded_edge_prefers_flood_prone():
    state = build_sample_state()
    edge_id = resolve_target("duong vao C001 bi ngap", EventType.FLOODED_AREA, state)
    assert edge_id == "DEPOT->C001#2"   # the flood-prone parallel edge


def test_resolves_traffic_edge_prefers_open():
    state = build_sample_state()
    edge_id = resolve_target("ket xe tren duong toi C001", EventType.TRAFFIC, state)
    assert edge_id == "DEPOT->C001"     # the open edge


def test_unresolved_returns_none():
    state = build_sample_state()
    assert resolve_target("khong khop voi gi ca", EventType.VEHICLE_BREAKDOWN, state) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.intake.resolver'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/intake/resolver.py`:

```python
"""Pure, deterministic resolver: free-text mention -> concrete world id.
Accent-folds Vietnamese so typed/transcribed text matches roster names."""

import re
import unicodedata
from typing import Optional

from fleet.contracts.state import WorldState, EventType, EdgeStatus

_EDGE_EVENTS = {EventType.TRAFFIC, EventType.FLOODED_AREA}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.casefold().strip()


def _match_vehicle(hint: str, state: WorldState) -> Optional[str]:
    n = _norm(hint)
    for vid in state.vehicles:
        if _norm(vid) in n:
            return vid
    m = re.search(r"\d+", n)
    if m:
        vid = f"V{int(m.group()):03d}"
        if vid in state.vehicles:
            return vid
    return None


def _match_customer(hint: str, state: WorldState) -> Optional[str]:
    n = _norm(hint)
    for cid in state.customers:
        if _norm(cid) in n:
            return cid
    for cid, c in state.customers.items():
        name = _norm(c.location.name)
        if name and (name in n or n in name):
            return cid
    return None


def _match_edge(hint: str, state: WorldState, event_type: EventType) -> Optional[str]:
    n = _norm(hint)
    for eid in state.road_graph.edges:
        if _norm(eid) == n:
            return eid
    cid = _match_customer(hint, state)
    if cid is None:
        return None
    candidates = (state.road_graph.edges_between("DEPOT", cid)
                  or state.road_graph.edges_between(cid, "DEPOT"))
    if not candidates:
        return None
    if event_type == EventType.FLOODED_AREA:
        flooded = [e for e in candidates
                   if e.flood_level > 0 or e.status == EdgeStatus.FLOODED]
        chosen = (flooded or candidates)[0]
    else:
        open_first = [e for e in candidates if e.status == EdgeStatus.OPEN]
        chosen = (open_first or candidates)[0]
    return chosen.id


def resolve_target(hint: str, event_type: EventType,
                   state: WorldState) -> Optional[str]:
    if event_type == EventType.VEHICLE_BREAKDOWN:
        return _match_vehicle(hint, state)
    if event_type in _EDGE_EVENTS:
        return _match_edge(hint, state, event_type)
    return _match_customer(hint, state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_intake_resolver.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add fleet/intake/resolver.py tests/test_intake_resolver.py
git commit -m "feat(intake): pure accent-folding target resolver"
```

---

## Task 3: LLM event extractor (pure prompt + parser)

Builds the (system, user) prompt embedding a compact world roster, defines the strict JSON schema, and parses the model's JSON into `list[IntakeReport]` (resolving targets, validating enums, dropping unresolved reports). A single utterance may yield multiple reports.

**Files:**
- Create: `fleet/intake/extractor.py`
- Test: `tests/test_intake_extractor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_extractor.py`:

```python
import pytest

from fleet.intake.extractor import build_intake_messages, parse_intake, _INTAKE_SCHEMA
from fleet.scenarios import build_sample_state
from fleet.contracts.state import EventType, EventSeverity, EdgeStatus


def test_build_messages_lists_world_and_enums():
    state = build_sample_state()
    system, user = build_intake_messages("xe 3 hong", state)
    assert "vehicle_breakdown" in system and "flooded_area" in system
    assert "V003" in user and "C001" in user          # roster present
    assert "xe 3 hong" in user                         # report text present


def test_parse_splits_multiple_reports():
    state = build_sample_state()
    data = {"reports": [
        {"event_type": "flooded_area", "target_hint": "duong vao C001",
         "severity": "high", "edge_status": "flooded", "flood_level": 0.6},
        {"event_type": "vehicle_breakdown", "target_hint": "xe 3",
         "severity": "high", "confidence": 0.9},
    ]}
    reports = parse_intake(data, state, raw_text="src")
    assert len(reports) == 2
    flood = reports[0]
    assert flood.event_type == EventType.FLOODED_AREA
    assert flood.target == "DEPOT->C001#2"
    assert flood.edge_status == EdgeStatus.FLOODED and flood.flood_level == 0.6
    veh = reports[1]
    assert veh.event_type == EventType.VEHICLE_BREAKDOWN and veh.target == "V003"
    assert veh.confidence == 0.9 and veh.raw_text == "src"


def test_parse_drops_unresolved_target():
    state = build_sample_state()
    data = {"reports": [
        {"event_type": "vehicle_breakdown", "target_hint": "khong ton tai",
         "severity": "low"}]}
    assert parse_intake(data, state, raw_text="") == []


def test_parse_raises_on_bad_enum():
    state = build_sample_state()
    data = {"reports": [
        {"event_type": "not_a_type", "target_hint": "C001", "severity": "low"}]}
    with pytest.raises(ValueError):
        parse_intake(data, state, raw_text="")


def test_schema_enumerates_all_event_types():
    et = _INTAKE_SCHEMA["properties"]["reports"]["items"]["properties"]["event_type"]
    assert set(et["enum"]) == {e.value for e in EventType}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.intake.extractor'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/intake/extractor.py`:

```python
"""Pure LLM-extractor helpers: build the prompt + schema, parse model JSON into
IntakeReports. No I/O — the transport is injected by the controller."""

from typing import List, Tuple

from fleet.contracts.state import (
    WorldState, EventType, EventSeverity, EdgeStatus,
)
from fleet.intake.report import IntakeReport
from fleet.intake.resolver import resolve_target

_INTAKE_SCHEMA = {
    "type": "object",
    "properties": {
        "reports": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string",
                                   "enum": [e.value for e in EventType]},
                    "target_hint": {"type": "string"},
                    "severity": {"type": "string",
                                 "enum": [s.value for s in EventSeverity]},
                    "confidence": {"type": "number"},
                    "edge_status": {"type": "string",
                                    "enum": [s.value for s in EdgeStatus]},
                    "flood_level": {"type": "number"},
                    "traffic_factor": {"type": "number"},
                },
                "required": ["event_type", "target_hint", "severity"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reports"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You convert a dispatcher's free-text field report into structured "
    "disruption events for a delivery-fleet system. Identify every distinct "
    "disruption in the report. For each, choose one event_type from "
    + ", ".join(e.value for e in EventType)
    + " and a severity from " + ", ".join(s.value for s in EventSeverity)
    + ". `target_hint` must quote the customer, vehicle, or road the report "
    "names so it can be matched to the world roster. For traffic/flooded_area "
    "set edge_status and flood_level/traffic_factor when stated. Respond using "
    "the provided JSON schema only."
)


def _roster(state: WorldState) -> str:
    customers = "; ".join(f"{cid}={c.location.name}"
                          for cid, c in state.customers.items())
    vehicles = ", ".join(state.vehicles.keys())
    edges = ", ".join(state.road_graph.edges.keys())
    return (f"Customers: {customers}\nVehicles: {vehicles}\n"
            f"Road edges: {edges}")


def build_intake_messages(text: str, state: WorldState) -> Tuple[str, str]:
    """Return (system, user) prompt strings. Pure: deterministic given text+state."""
    user = (f"World roster:\n{_roster(state)}\n\n"
            f"Field report: {text}\n"
            "Extract all disruption events as JSON.")
    return _SYSTEM, user


def parse_intake(data: dict, state: WorldState,
                 raw_text: str = "") -> List[IntakeReport]:
    """Map model JSON to IntakeReports. Validates enums (raises ValueError on a
    bad event_type/severity), resolves targets, drops reports whose target can
    not be resolved against the world."""
    out: List[IntakeReport] = []
    for item in data.get("reports", []):
        event_type = EventType(item["event_type"])        # ValueError if unknown
        severity = EventSeverity(item["severity"])        # ValueError if unknown
        target = resolve_target(item.get("target_hint", ""), event_type, state)
        if target is None:
            continue
        edge_status = (EdgeStatus(item["edge_status"])
                       if item.get("edge_status") else None)
        out.append(IntakeReport(
            event_type=event_type, target=target, severity=severity,
            raw_text=raw_text,
            confidence=float(item.get("confidence", 1.0)),
            edge_status=edge_status,
            flood_level=float(item.get("flood_level", 0.0)),
            traffic_factor=float(item.get("traffic_factor", 1.0)),
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_intake_extractor.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add fleet/intake/extractor.py tests/test_intake_extractor.py
git commit -m "feat(intake): LLM event extractor (prompt + schema + parser)"
```

---

## Task 4: Transcriber interface + impls

Audio→text behind a tiny interface, with an injected `transcribe_fn` so tests never import torch/whisper/riva. `WhisperTranscriber` (self-host, Vietnamese-strong, no entitlement) and `RivaTranscriber` (NIM, premium) build their default callable lazily; `NullTranscriber` is the text-only default.

**Files:**
- Create: `fleet/intake/asr.py`
- Test: `tests/test_intake_asr.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_asr.py`:

```python
import pytest

from fleet.intake.asr import (
    WhisperTranscriber, RivaTranscriber, NullTranscriber,
)


def test_injected_transcribe_fn_is_used():
    t = WhisperTranscriber(transcribe_fn=lambda audio, lang: f"heard:{len(audio)}:{lang}")
    assert t.transcribe(b"abc", "vi") == "heard:3:vi"


def test_riva_injected_fn_is_used():
    t = RivaTranscriber(transcribe_fn=lambda audio, lang: "riva-text")
    assert t.transcribe(b"x", "vi") == "riva-text"


def test_null_transcriber_raises():
    with pytest.raises(RuntimeError):
        NullTranscriber().transcribe(b"x", "vi")


def test_whisper_without_fn_or_model_raises():
    class _S:  # settings stub with no whisper model configured
        whisper_model = ""
    with pytest.raises(RuntimeError):
        WhisperTranscriber(settings=_S()).transcribe(b"x", "vi")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_asr.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.intake.asr'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/intake/asr.py`:

```python
"""Transcriber interface + impls. The transcribe callable is injected so the
suite never imports a speech model; default callables are built lazily."""

from typing import Callable, Optional, Protocol, runtime_checkable

TranscribeFn = Callable[[bytes, str], str]


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(self, audio: bytes, lang: str) -> str: ...


class NullTranscriber:
    """Text-only default: audio reporting disabled."""

    def transcribe(self, audio: bytes, lang: str) -> str:
        raise RuntimeError("ASR disabled (ASR_ENGINE=none); use the text box.")


class WhisperTranscriber:
    """Self-hosted Whisper (no NGC entitlement needed). `transcribe_fn` injected
    for tests; the default loads faster-whisper lazily from settings.whisper_model."""

    def __init__(self, settings=None, transcribe_fn: Optional[TranscribeFn] = None):
        self.settings = settings
        self._fn = transcribe_fn

    def transcribe(self, audio: bytes, lang: str) -> str:
        return self._get_fn()(audio, lang)

    def _get_fn(self) -> TranscribeFn:
        if self._fn is None:
            self._fn = self._build_default_fn()
        return self._fn

    def _build_default_fn(self) -> TranscribeFn:
        model_name = getattr(self.settings, "whisper_model", "") or ""
        if not model_name:
            raise RuntimeError(
                "WhisperTranscriber has no transcribe_fn and settings.whisper_model "
                "is empty; configure WHISPER_MODEL or inject a callable.")
        import io
        from faster_whisper import WhisperModel  # optional dep

        model = WhisperModel(model_name, device="cuda", compute_type="float16")

        def fn(audio: bytes, lang: str) -> str:
            segments, _ = model.transcribe(io.BytesIO(audio), language=lang)
            return " ".join(s.text for s in segments).strip()

        return fn


class RivaTranscriber:
    """NVIDIA Riva ASR NIM (premium). `transcribe_fn` injected for tests; the
    default builds a Riva gRPC client lazily from settings.riva_endpoint."""

    def __init__(self, settings=None, transcribe_fn: Optional[TranscribeFn] = None):
        self.settings = settings
        self._fn = transcribe_fn

    def transcribe(self, audio: bytes, lang: str) -> str:
        return self._get_fn()(audio, lang)

    def _get_fn(self) -> TranscribeFn:
        if self._fn is None:
            self._fn = self._build_default_fn()
        return self._fn

    def _build_default_fn(self) -> TranscribeFn:
        endpoint = getattr(self.settings, "riva_endpoint", "") or ""
        if not endpoint:
            raise RuntimeError(
                "RivaTranscriber has no transcribe_fn and settings.riva_endpoint "
                "is empty; configure RIVA_ENDPOINT or inject a callable.")
        import riva.client  # optional dep

        auth = riva.client.Auth(uri=endpoint)
        asr = riva.client.ASRService(auth)

        def fn(audio: bytes, lang: str) -> str:
            config = riva.client.RecognitionConfig(language_code=lang,
                                                   max_alternatives=1)
            resp = asr.offline_recognize(audio, config)
            return " ".join(r.alternatives[0].transcript
                            for r in resp.results).strip()

        return fn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_intake_asr.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add fleet/intake/asr.py tests/test_intake_asr.py
git commit -m "feat(intake): Transcriber interface (Whisper/Riva/Null, injected transport)"
```

---

## Task 5: IntakeController orchestration

Wires sensor → extractor → injection → `step`. Edge events go through `disrupt_edge` (so the routing matrix actually changes); node/vehicle events through `inject_event`. The `complete` transport and `Transcriber` are injected; a lazy default `complete` mirrors `nim_agent`'s transport but pins `_INTAKE_SCHEMA`.

**Files:**
- Create: `fleet/intake/controller.py`
- Test: `tests/test_intake_controller.py` (replace the Task 1 smoke file)

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/test_intake_controller.py` with:

```python
import pytest

from fleet.intake.report import IntakeReport, IntakeResult
from fleet.intake.controller import IntakeController
from fleet.intake.asr import NullTranscriber
from fleet.ui.controller import SimulationController
from fleet.contracts.state import EventType, EventSeverity, EdgeStatus


def test_intake_report_defaults():
    r = IntakeReport(event_type=EventType.INVENTORY_SHORTAGE, target="C001",
                     severity=EventSeverity.HIGH, raw_text="kho C001 het hang")
    assert r.confidence == 1.0 and r.edge_status is None


def test_intake_result_holds_reports():
    res = IntakeResult(raw_text="x", reports=[], injected_event_ids=[], decisions=[])
    assert res.reports == [] and res.injected_event_ids == []


def _fake_complete(reports):
    return lambda system, user: {"reports": reports}


def test_text_report_injects_node_event_and_decides():
    sim = SimulationController()
    ic = IntakeController(sim, complete=_fake_complete([
        {"event_type": "inventory_shortage", "target_hint": "C001",
         "severity": "high"}]))
    result = ic.report(text="kho C001 het hang")
    assert len(result.injected_event_ids) == 1
    evt_id = result.injected_event_ids[0]
    # event landed in the world and the pipeline produced a decision for it
    assert any(e.id == evt_id for e in sim.state.events)
    assert any(d.event_id == evt_id for d in sim.state.decisions)


def test_edge_report_uses_disrupt_edge():
    sim = SimulationController()
    ic = IntakeController(sim, complete=_fake_complete([
        {"event_type": "flooded_area", "target_hint": "duong vao C001",
         "severity": "high", "edge_status": "flooded", "flood_level": 0.6}]))
    ic.report(text="duong vao C001 ngap")
    edge = sim.state.road_graph.get_edge("DEPOT->C001#2")
    assert edge.status == EdgeStatus.FLOODED and edge.flood_level == 0.6


def test_audio_path_transcribes_then_injects():
    sim = SimulationController()
    ic = IntakeController(
        sim,
        complete=_fake_complete([
            {"event_type": "vehicle_breakdown", "target_hint": "xe 3",
             "severity": "high"}]),
        transcriber=type("T", (), {"transcribe": lambda self, a, l: "xe 3 hong"})())
    result = ic.report(audio=b"\x00\x01")
    assert result.raw_text == "xe 3 hong"
    assert len(result.injected_event_ids) == 1


def test_bad_json_returns_empty_result_no_crash():
    sim = SimulationController()
    ic = IntakeController(sim, complete=lambda s, u: {"reports": [
        {"event_type": "not_a_type", "target_hint": "C001", "severity": "low"}]})
    result = ic.report(text="loi")
    assert result.injected_event_ids == [] and result.reports == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_intake_controller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.intake.controller'`

- [ ] **Step 3: Write minimal implementation**

Create `fleet/intake/controller.py`:

```python
"""Orchestrates a field report into the live world: transcribe (if audio) ->
extract -> inject via the existing simulator seam -> step the loop. Returns an
IntakeResult for the UI. Edge events use disrupt_edge; others use inject_event."""

from typing import Callable, Optional

from fleet.contracts.state import EventType, EdgeStatus
from fleet.intake.report import IntakeResult
from fleet.intake.asr import Transcriber, NullTranscriber
from fleet.intake.extractor import (
    build_intake_messages, parse_intake, _INTAKE_SCHEMA,
)

_EDGE_EVENTS = {EventType.TRAFFIC, EventType.FLOODED_AREA}
_DEFAULT_FLOOD_LEVEL = 0.5
_DEFAULT_TRAFFIC_FACTOR = 3.0


class IntakeController:
    """`complete(system, user) -> dict` and `transcriber` are injected so the
    path is testable offline. When `complete` is omitted it is built lazily from
    settings (NIM/Claude with the intake JSON schema)."""

    def __init__(self, sim, complete: Optional[Callable[[str, str], dict]] = None,
                 transcriber: Optional[Transcriber] = None):
        self.sim = sim                       # SimulationController
        self._complete = complete
        self.transcriber = transcriber or NullTranscriber()

    def report(self, text: Optional[str] = None, audio: Optional[bytes] = None,
               lang: str = "vi") -> IntakeResult:
        raw = text or ""
        if audio is not None:
            raw = self.transcriber.transcribe(audio, lang)

        state = self.sim.state
        simulator = self.sim.components.simulator
        try:
            system, user = build_intake_messages(raw, state)
            data = self._get_complete()(system, user)
            reports = parse_intake(data, state, raw_text=raw)
        except Exception:
            reports = []

        injected = []
        for r in reports:
            if r.event_type in _EDGE_EVENTS:
                if r.event_type == EventType.FLOODED_AREA:
                    status = r.edge_status or EdgeStatus.FLOODED
                    evt = simulator.disrupt_edge(
                        state, r.target, status,
                        flood_level=r.flood_level or _DEFAULT_FLOOD_LEVEL)
                else:
                    status = r.edge_status or EdgeStatus.CONGESTED
                    evt = simulator.disrupt_edge(
                        state, r.target, status,
                        traffic_factor=r.traffic_factor or _DEFAULT_TRAFFIC_FACTOR)
            else:
                evt = simulator.inject_event(state, r.event_type, r.target,
                                             r.severity)
            injected.append(evt.id)

        self.sim.step(1)
        return IntakeResult(
            raw_text=raw, reports=reports, injected_event_ids=injected,
            decisions=self.sim.snapshot()["pending_decisions"])

    def _get_complete(self) -> Callable[[str, str], dict]:
        if self._complete is None:
            self._complete = build_intake_complete(self.sim.settings)
        return self._complete


def build_intake_complete(settings) -> Callable[[str, str], dict]:
    """Lazy transport for the extractor: a NIM (OpenAI-compatible) or Claude call
    constrained to _INTAKE_SCHEMA. Mirrors nim_agent/claude_agent; imports the
    optional client only when actually built."""
    engine = getattr(settings, "intake_extractor", "nim")
    if engine == "claude" and getattr(settings, "anthropic_api_key", ""):
        import json
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        def complete(system: str, user: str) -> dict:
            resp = client.messages.create(
                model="claude-opus-4-8", max_tokens=1024,
                thinking={"type": "adaptive"}, system=system,
                output_config={"format": {"type": "json_schema",
                                          "schema": _INTAKE_SCHEMA}},
                messages=[{"role": "user", "content": user}])
            text = next(b.text for b in resp.content if b.type == "text")
            return json.loads(text)
        return complete

    endpoint = getattr(settings, "nim_endpoint", "") or ""
    if not endpoint:
        raise RuntimeError(
            "intake extractor has no transport: set NIM_ENDPOINT (or "
            "INTAKE_EXTRACTOR=claude + ANTHROPIC_API_KEY), or inject `complete`.")
    import json
    from openai import OpenAI
    client = OpenAI(base_url=endpoint, api_key="not-needed")
    model = getattr(settings, "nim_model", "") or ""

    def complete(system: str, user: str) -> dict:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.0,
            extra_body={"nvext": {"guided_json": _INTAKE_SCHEMA}})
        return json.loads(resp.choices[0].message.content)
    return complete
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_intake_controller.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the full suite to confirm nothing regressed**

Run: `python -m pytest -q`
Expected: all prior tests still pass (255+) plus the new intake tests.

- [ ] **Step 6: Commit**

```bash
git add fleet/intake/controller.py tests/test_intake_controller.py
git commit -m "feat(intake): IntakeController orchestration + lazy extractor transport"
```

---

## Task 6: Settings + factory wiring

Add the 4 intake settings (all defaulting to the OFF / text-only path) and a `build_transcriber(settings)` selector returning `NullTranscriber` by default.

**Files:**
- Modify: `config/settings.py` (dataclass fields + `load_settings` parsing)
- Modify: `fleet/factory.py` (`build_transcriber`)
- Test: `tests/test_factory.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_factory.py`:

```python
def test_build_transcriber_defaults_to_null():
    from config.settings import load_settings
    from fleet.factory import build_transcriber
    from fleet.intake.asr import NullTranscriber
    t = build_transcriber(load_settings({}))
    assert isinstance(t, NullTranscriber)


def test_build_transcriber_selects_whisper():
    from config.settings import load_settings
    from fleet.factory import build_transcriber
    from fleet.intake.asr import WhisperTranscriber
    t = build_transcriber(load_settings({"ASR_ENGINE": "whisper"}))
    assert isinstance(t, WhisperTranscriber)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory.py -k transcriber -v`
Expected: FAIL with `ImportError: cannot import name 'build_transcriber'`

- [ ] **Step 3: Write minimal implementation**

In `config/settings.py`, add these fields to the `Settings` dataclass (after `nim_model`):

```python
    asr_engine: str = "none"          # intake: none | whisper | riva
    riva_endpoint: str = ""           # intake: Riva ASR NIM endpoint
    whisper_model: str = "large-v3"   # intake: faster-whisper model id
    intake_extractor: str = "nim"     # intake: nim | claude (extractor transport)
```

In `config/settings.py`, add these to the `return Settings(...)` call in `load_settings` (after `nim_model=...`):

```python
        asr_engine=e.get("ASR_ENGINE", "none"),
        riva_endpoint=e.get("RIVA_ENDPOINT", ""),
        whisper_model=e.get("WHISPER_MODEL", "large-v3"),
        intake_extractor=e.get("INTAKE_EXTRACTOR", "nim"),
```

In `fleet/factory.py`, add the import near the other impl imports:

```python
from fleet.intake.asr import NullTranscriber, WhisperTranscriber, RivaTranscriber
```

In `fleet/factory.py`, add this function at the end of the module:

```python
def build_transcriber(settings):
    """Select the ASR impl. Defaults to NullTranscriber (text-only) so the
    feature is OFF unless ASR_ENGINE is set."""
    if settings.asr_engine == "whisper":
        return WhisperTranscriber(settings)
    if settings.asr_engine == "riva" and getattr(settings, "riva_endpoint", ""):
        return RivaTranscriber(settings)
    return NullTranscriber()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory.py -k transcriber -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: all green (existing + intake + factory).

- [ ] **Step 6: Commit**

```bash
git add config/settings.py fleet/factory.py tests/test_factory.py
git commit -m "feat(intake): settings + build_transcriber factory (defaults OFF)"
```

---

## Task 7: Streamlit "Báo cáo sự cố" panel + requirements

Add a panel to the existing app that accepts mic, audio-file upload, and typed text; shows the transcript + extracted reports; injects on a button; and renders a decision card (`action` + `reasoning` + `engine`). Streamlit is imported only in `app.py` so tests never import it — this task is **manual smoke only**.

**Files:**
- Modify: `fleet/ui/app.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Inspect the current app structure**

Run: `python -c "import pathlib; print(pathlib.Path('fleet/ui/app.py').read_text(encoding='utf-8'))"`
Expected: prints the current Streamlit app so you can see how `SimulationController` is held in `st.session_state` and where to add a section.

- [ ] **Step 2: Add the intake panel**

In `fleet/ui/app.py`, after the existing controls/metrics section, add (adapt variable names to the existing controller handle in session state, typically `st.session_state.controller`):

```python
import streamlit as st  # already imported at top of app.py
from fleet.intake.controller import IntakeController
from fleet.factory import build_transcriber


def render_intake_panel(controller):
    st.subheader("Báo cáo sự cố (giọng nói / văn bản)")
    audio = st.audio_input("Nói mô tả sự cố")               # mic
    uploaded = st.file_uploader("…hoặc tải file âm thanh", type=["wav", "mp3", "m4a"])
    text = st.text_area("…hoặc gõ mô tả", placeholder="VD: đường vào C001 ngập, xe 3 hỏng")

    if st.button("Bóc tách & xử lý"):
        ic = IntakeController(controller,
                              transcriber=build_transcriber(controller.settings))
        audio_bytes = None
        if audio is not None:
            audio_bytes = audio.getvalue()
        elif uploaded is not None:
            audio_bytes = uploaded.getvalue()
        try:
            result = ic.report(text=text or None, audio=audio_bytes)
        except Exception as exc:                            # ASR/extractor failure
            st.error(f"Không xử lý được báo cáo: {exc}")
            return

        if result.raw_text:
            st.caption(f"Đã nghe/đọc: “{result.raw_text}”")
        if not result.reports:
            st.warning("Không bóc tách được sự cố nào hợp lệ. Hãy nói/gõ rõ hơn.")
        for r in result.reports:
            st.success(f"➕ {r.event_type.value} · {r.target} · {r.severity.value}")
        for d in result.decisions:
            with st.container(border=True):
                st.markdown(f"**Quyết định:** {d['action']} — {d.get('description','')}")
                st.caption(f"engine={d.get('engine','')} · "
                           f"+{d.get('added_delay_min', 0)} phút")
```

Then call `render_intake_panel(st.session_state.controller)` in the main body where the other sections are rendered. (Note: the snapshot's `pending_decisions` items do not include `engine`/`reasoning`; if you want those on the card, read them from `controller.state.decisions` for the matching `event_id` — optional polish.)

- [ ] **Step 3: Add optional-dependency comments to requirements**

In `requirements.txt`, append:

```text
# --- intake layer (optional, lazy-imported; not needed for the test suite) ---
# openai>=1.0          # OpenAI-compatible client for the NIM extractor transport
# faster-whisper>=1.0  # self-hosted Vietnamese ASR (WhisperTranscriber)
# nvidia-riva-client   # Riva ASR NIM transport (RivaTranscriber)
```

- [ ] **Step 4: Manual smoke**

Run: `python -m streamlit run fleet/ui/app.py`
Expected: the app loads; the "Báo cáo sự cố" panel renders with a mic input, file uploader, and text area. Typing `kho C001 het hang` and clicking the button (with `NIM_ENDPOINT` set, or after wiring a fake) injects an event and shows a decision card. Without a transport configured it shows a clear error — confirming graceful degradation.

- [ ] **Step 5: Run the full suite (must not import streamlit)**

Run: `python -m pytest -q`
Expected: all green; the suite never imports streamlit (panel code lives only in `app.py`).

- [ ] **Step 6: Commit**

```bash
git add fleet/ui/app.py requirements.txt
git commit -m "feat(intake): Streamlit field-report panel (mic/upload/text) + decision card"
```

---

## Definition of Done

- `python -m pytest -q` is green: existing suite (255+) plus new intake tests, with no test importing torch/whisper/riva/openai/streamlit.
- Default path unchanged: with no `ASR_ENGINE`/`NIM_ENDPOINT`, the system runs exactly as before; `build_transcriber` returns `NullTranscriber`.
- A typed or spoken report resolves to a concrete target, injects the correct event via `disrupt_edge`/`inject_event`, and produces a decision visible in the UI.
- The panel degrades gracefully (clear error) when ASR or the extractor transport is unavailable.

## Notes for the executor

- **Resource check before any live-model run** (non-blocking for the code/tests): on node-07 confirm a Riva ASR NIM can be pulled (else keep `ASR_ENGINE=whisper`), that `faster-whisper` can fetch `large-v3` into `/raid`, and that a web port can be exposed for the demo. The whole suite and the text-only path need none of these.
- **Live extractor** uses the already-deployed Nemotron NIM: run the UI with `DECISION_ENGINE=nim NIM_ENDPOINT=http://localhost:8000/v1` and the extractor reuses that endpoint via `build_intake_complete`.
- Keep the feature OFF by default; never change `inject_event`/`disrupt_edge`/loop signatures.
