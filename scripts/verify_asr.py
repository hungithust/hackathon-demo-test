"""Standalone ASR smoke test for the Parakeet/Riva ASR NIM — voice-model branch.

Connects to the Riva-compatible gRPC endpoint exposed by the ASR NIM
(nvcr.io/nim/nvidia/parakeet-1-1b-ctc-en-us), transcribes one audio file, and
prints the text. Touches nothing in the reroute pipeline: it only exercises
fleet.intake.asr.RivaTranscriber.

On the H200, start the NIM first (it is NOT running yet):

    docker run --rm -it --gpus all \\
      -p 50051:50051 -p 9000:9000 \\
      nvcr.io/nim/nvidia/parakeet-1-1b-ctc-en-us:latest
    # wait for "Riva server is ready" in the logs

Then verify (Parakeet is English):

    RIVA_ENDPOINT=localhost:50051 python -m scripts.verify_asr --audio sample_en.wav
"""

import argparse
import os
import time

from fleet.intake.asr import RivaTranscriber


def main():
    p = argparse.ArgumentParser(description="ASR NIM connectivity smoke test")
    p.add_argument("--audio", required=True,
                   help="path to an audio file (16kHz mono wav recommended)")
    p.add_argument("--endpoint", default=os.environ.get("RIVA_ENDPOINT", "localhost:50051"),
                   help="Riva gRPC endpoint host:port (default $RIVA_ENDPOINT or localhost:50051)")
    p.add_argument("--lang", default="en-US",
                   help="language code (Parakeet en-US NIM -> en-US)")
    args = p.parse_args()

    with open(args.audio, "rb") as f:
        audio = f.read()

    print(f"endpoint = {args.endpoint}")
    print(f"audio    = {args.audio} ({len(audio)} bytes)")
    print(f"lang     = {args.lang}")

    class _S:
        riva_endpoint = args.endpoint

    transcriber = RivaTranscriber(settings=_S())

    t0 = time.perf_counter()
    text = transcriber.transcribe(audio, args.lang)
    dt = time.perf_counter() - t0

    print(f"\n--- transcript ({dt:.2f}s) ---\n{text!r}")
    if not text.strip():
        print("\nWARNING: empty transcript. Check the audio format (16kHz mono "
              "PCM wav) and that the NIM finished loading the model.")


if __name__ == "__main__":
    main()
