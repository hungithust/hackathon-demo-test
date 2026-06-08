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
