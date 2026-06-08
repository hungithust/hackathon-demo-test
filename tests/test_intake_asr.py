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
