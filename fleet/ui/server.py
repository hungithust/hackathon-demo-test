"""FastAPI control-room server (replaces the M7 Streamlit app).

Serves the static React control room (fleet/ui/web/) and a thin JSON API over the
headless simulation. All logic stays in SimulationController / IntakeController —
this module is glue + transport only, so the headless system and the test suite
never depend on FastAPI.

    uvicorn fleet.ui.server:app --reload          # dev
    python -m fleet.ui.server                      # convenience launcher

The simulation is a single in-memory session (one dispatcher, one screen), matching
the original Streamlit model. POST /api/reset rebuilds it.
"""

import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fleet.ui.controller import SimulationController
from fleet.intake.controller import IntakeController
from fleet.factory import build_transcriber
from config import settings_schema

_WEB = Path(__file__).resolve().parent / "web"

app = FastAPI(title="FleetOps Control Room")

# Single shared session (rebuilt by /api/reset).
_ctrl = SimulationController()

# Serialize every request that touches the shared session.  FastAPI runs sync
# endpoints in a threadpool, so without this an approve / step / report could
# mutate state.decisions / state.plan concurrently — corrupting the snapshot
# (e.g. a decision that survives approval, or a scrambled re-solve).
_lock = threading.Lock()

# Settings overrides applied via the UI ({} == all defaults from os.environ).
_overrides: dict = {}


def _build_settings():
    return settings_schema.apply(_overrides)


def _controller() -> SimulationController:
    return _ctrl


# --------------------------------------------------------------------------
# Offline extractor fallback: when no NIM/Claude transport is configured, parse
# the field report with regex so the voice/text intake still works in a demo.
# Returns the _INTAKE_SCHEMA shape, so it flows through the real intake pipeline.
# --------------------------------------------------------------------------
def _regex_complete(system: str, user: str) -> dict:
    # The user prompt embeds "Field report: <text>"; isolate it so the roster
    # (which lists every customer) doesn't pollute keyword/target matching.
    m = re.search(r"Field report:\s*(.*)", user)
    report = (m.group(1).split("\n", 1)[0] if m else user).strip()
    low = " " + report.lower() + " "

    def sev(default: str) -> str:
        if re.search(r"critical|severe|major|nghi[eê]m tr[oọ]ng|n[ặa]ng", low):
            return "critical"
        if re.search(r"\bhigh\b|bad|heavy|l[ơo]n|l[ớo]n", low):
            return "high"
        if re.search(r"minor|light|nh[ẹe]", low):
            return "low"
        return default

    reports = []

    def add(event_type, severity, **extra):
        reports.append({"event_type": event_type, "target_hint": report,
                        "severity": severity, **extra})

    if re.search(r"flood|ng[ậâ]p|water|n[ưu][ơo]c", low):
        add("flooded_area", sev("high"), edge_status="flooded", flood_level=0.5)
    if re.search(r"broke|broken|breakdown|h[ỏo]ng|h[ưu] h[ỏo]ng|stall", low):
        add("vehicle_breakdown", sev("high"))
    if re.search(r"traffic|jam|congest|k[ẹe]t|t[ắa]c", low):
        add("traffic", sev("medium"), edge_status="congested", traffic_factor=15.0)
    if re.search(r"urgent|asap|g[ấâ]p|kh[ẩâ]n", low):
        add("urgent_order", sev("high"))
    if re.search(r"surge|spike|rush|t[ăa]ng", low):
        add("demand_surge", sev("medium"))
    if re.search(r"shortage|out of stock|thi[ếe]u|h[ếe]t h[àa]ng|restock", low):
        add("inventory_shortage", sev("medium"))
    return {"reports": reports}


def _intake_complete(settings) -> Optional[Callable[[str, str], dict]]:
    """Real NIM/Claude transport if configured, else the regex fallback."""
    from fleet.intake.controller import build_intake_complete
    try:
        return build_intake_complete(settings)
    except RuntimeError:
        return _regex_complete


# ---------------- API ----------------
class StepBody(BaseModel):
    n: int = 1


class ReportBody(BaseModel):
    text: str = ""


class SettingsBody(BaseModel):
    values: dict = {}


@app.get("/api/snapshot")
def get_snapshot():
    with _lock:
        return _controller().snapshot()


@app.post("/api/step")
def post_step(body: StepBody):
    with _lock:
        c = _controller()
        c.step(max(1, min(int(body.n), 50)))
        return c.snapshot()


@app.post("/api/approve/{decision_id}")
def post_approve(decision_id: str):
    with _lock:
        c = _controller()
        try:
            c.approve(decision_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such pending decision")
        return c.snapshot()


@app.post("/api/reject/{decision_id}")
def post_reject(decision_id: str):
    with _lock:
        c = _controller()
        try:
            c.reject(decision_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such pending decision")
        return c.snapshot()


def _report_payload(result, c) -> dict:
    return {
        "raw": result.raw_text,
        "reports": [{"event_type": r.event_type.value, "target": r.target,
                     "severity": r.severity.value} for r in result.reports],
        "decisions": result.decisions,
        "snapshot": c.snapshot(),
    }


@app.post("/api/report")
def post_report(body: ReportBody):
    with _lock:
        c = _controller()
        ic = IntakeController(c, complete=_intake_complete(c.settings),
                              transcriber=build_transcriber(c.settings))
        result = ic.report(text=body.text or None)
        return _report_payload(result, c)


def _transcode_to_pcm16(raw: bytes, rate: int = 16000) -> bytes:
    """Decode any browser audio blob (typically WebM/Opus) to headerless 16kHz
    mono signed-16-bit PCM, exactly what the Riva LINEAR_PCM stream expects."""
    if shutil.which("ffmpeg") is None:
        raise HTTPException(
            status_code=503,
            detail="ffmpeg not found on the server; cannot decode mic audio.")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-ar", str(rate), "-ac", "1", "-f", "s16le", "pipe:1"],
        input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not proc.stdout:
        raise HTTPException(
            status_code=400,
            detail="could not decode the audio: "
                   + proc.stderr.decode("utf-8", "ignore")[:300])
    return proc.stdout


@app.post("/api/report_audio")
def post_report_audio(audio: UploadFile = File(...), lang: str = "en-US"):
    # Sync endpoint (runs in the threadpool) so the slow ffmpeg + ASR work happens
    # WITHOUT holding _lock; only the world mutation below is serialized.
    c = _controller()
    transcriber = build_transcriber(c.settings)
    if transcriber.__class__.__name__ == "NullTranscriber":
        raise HTTPException(
            status_code=503,
            detail="ASR is disabled. Start the server with ASR_ENGINE=riva and "
                   "RIVA_ENDPOINT set (or ASR_ENGINE=whisper).")
    pcm = _transcode_to_pcm16(audio.file.read())
    raw = transcriber.transcribe(pcm, lang)        # slow; kept outside the lock
    with _lock:
        ic = IntakeController(c, complete=_intake_complete(c.settings))
        result = ic.report(text=raw or None, lang=lang)
        return _report_payload(result, c)


@app.get("/api/settings")
def get_settings():
    groups = []
    for s in settings_schema.build_specs():
        g = next((x for x in groups if x["name"] == s.group), None)
        if g is None:
            g = {"name": s.group, "fields": []}
            groups.append(g)
        g["fields"].append({
            "key": s.key, "label": s.label, "type": s.type,
            "choices": list(s.choices), "step": s.step,
            "advanced": s.advanced, "help": s.help,
        })
    return {"groups": groups, "values": settings_schema.current_values(_build_settings())}


@app.post("/api/settings")
def post_settings(body: SettingsBody):
    global _ctrl, _overrides
    merged = {**_overrides, **body.values}
    try:
        new_settings = settings_schema.apply(merged)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    with _lock:
        _overrides = merged
        _ctrl = SimulationController(settings=new_settings)
        return _ctrl.snapshot()


@app.post("/api/reset")
def post_reset():
    global _ctrl
    with _lock:
        _ctrl = SimulationController(settings=_build_settings())
        return _ctrl.snapshot()


# ---------------- static web app ----------------
@app.get("/")
def index():
    return FileResponse(_WEB / "index.html")


app.mount("/", StaticFiles(directory=str(_WEB)), name="web")


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8686)


if __name__ == "__main__":
    main()
