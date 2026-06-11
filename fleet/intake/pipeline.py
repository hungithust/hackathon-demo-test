"""Extract-only voice->event path: transcribe (if audio) -> LLM extract ->
IntakeReports, WITHOUT injecting into the world.

This lets the voice model be developed and tested independently of the reroute
pipeline: it never calls inject_event/disrupt_edge/step, and needs only a
WorldState (for the roster + target resolution), not a SimulationController.
"""

from typing import Callable, List, Optional, Tuple

from fleet.contracts.state import WorldState
from fleet.intake.asr import Transcriber, NullTranscriber
from fleet.intake.extractor import build_intake_messages, parse_intake
from fleet.intake.report import IntakeReport


def extract_reports(
    state: WorldState,
    complete: Callable[[str, str], dict],
    *,
    text: Optional[str] = None,
    audio: Optional[bytes] = None,
    lang: str = "en-US",
    transcriber: Optional[Transcriber] = None,
) -> Tuple[str, List[IntakeReport]]:
    """Return (raw_text, reports). `complete(system, user) -> dict` and
    `transcriber` are injected so this is fully offline-testable. When `audio`
    is given it is transcribed first; otherwise `text` is used as-is."""
    raw = text or ""
    if audio is not None:
        raw = (transcriber or NullTranscriber()).transcribe(audio, lang)
    system, user = build_intake_messages(raw, state)
    data = complete(system, user)
    reports = parse_intake(data, state, raw_text=raw)
    return raw, reports
