"""End-to-end voice->event CLI (no injection): audio file -> RIVA ASR ->
LLM extract -> IntakeReports. Exercises the full intake understanding path
against a live ASR NIM + extractor, without touching the reroute pipeline.

  # extractor via the local Nemotron NIM (port 8002)
  RIVA_ENDPOINT=localhost:50051 python -m scripts.extract_from_audio \\
      --audio sample_16k.wav --extractor nim

  # or via Claude (uses ANTHROPIC_API_KEY from the environment / .env)
  RIVA_ENDPOINT=localhost:50051 ANTHROPIC_API_KEY=sk-... \\
      python -m scripts.extract_from_audio --audio sample_16k.wav --extractor claude
"""

import argparse
import os

from config.settings import load_settings
from fleet.scenarios import build_sample_state
from fleet.intake.asr import RivaTranscriber
from fleet.intake.controller import build_intake_complete
from fleet.intake.pipeline import extract_reports


def main():
    p = argparse.ArgumentParser(description="voice -> event (extract-only)")
    p.add_argument("--audio", required=True, help="16kHz mono PCM wav")
    p.add_argument("--lang", default="en-US")
    p.add_argument("--riva-endpoint",
                   default=os.environ.get("RIVA_ENDPOINT", "localhost:50051"))
    p.add_argument("--extractor", choices=["nim", "claude"], default="nim")
    p.add_argument("--text", help="skip ASR, extract from this text instead")
    args = p.parse_args()

    env = dict(os.environ)
    env.update(RIVA_ENDPOINT=args.riva_endpoint, ASR_ENGINE="riva",
               INTAKE_EXTRACTOR=args.extractor)
    settings = load_settings(env)

    state = build_sample_state()
    complete = build_intake_complete(settings)
    transcriber = RivaTranscriber(settings)

    audio = None
    if not args.text:
        with open(args.audio, "rb") as f:
            audio = f.read()

    raw, reports = extract_reports(
        state, complete, text=args.text, audio=audio,
        lang=args.lang, transcriber=transcriber)

    print(f"\n--- transcript ---\n{raw!r}")
    print(f"\n--- {len(reports)} report(s) ---")
    for r in reports:
        line = (f"  {r.event_type.value} | target={r.target} | "
                f"severity={r.severity.value} | conf={r.confidence}")
        if r.edge_status is not None:
            line += (f" | edge_status={r.edge_status.value} "
                     f"flood={r.flood_level} traffic={r.traffic_factor}")
        print(line)
    if not reports:
        print("  (none resolved — check roster match / extractor output)")


if __name__ == "__main__":
    main()
