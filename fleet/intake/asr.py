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
