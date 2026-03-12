"""Chatterbox TTS backends for the audio agent.

Two backends share the same synthesize()/close() interface:

  ChatterboxDirectBackend  — loads ChatterboxTurboTTS in-process on the GPU.
                             Serial-only: not safe to call generate() from
                             multiple threads on the same instance.

  ChatterboxServerBackend  — HTTP client for the FastAPI server in
                             vendor/chatterbox/app/main.py. Reuses the retry
                             session from tts_tools so retry/backoff behaviour
                             is consistent with the ElevenLabs backend.

Both raise TTSError on failure so AudioAgent's existing exception handling
applies unchanged.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import requests

from .tts_tools import TTSError, _get_retry_session


@dataclass
class TTSRequest:
    """Request object for Chatterbox TTS backends.

    Fields mirror the POST /tts JSON body accepted by the chatterbox server.
    """

    text: str
    temperature: float = 0.8
    top_p: float = 0.95
    top_k: int = 1000
    repetition_penalty: float = 1.2

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "repetition_penalty": self.repetition_penalty,
        }


class ChatterboxDirectBackend:
    """In-process GPU backend.

    Loads ChatterboxTurboTTS once at construction and serialises all generate()
    calls through this single instance. Must not be shared across threads.
    """

    def __init__(self) -> None:
        try:
            from chatterbox.tts_turbo import ChatterboxTurboTTS
        except ImportError as e:
            raise TTSError(f"chatterbox package not installed: {e}") from e

        try:
            self._model = ChatterboxTurboTTS.from_pretrained(device="cuda")
        except Exception as e:
            raise TTSError(f"Failed to load ChatterboxTurboTTS: {e}") from e

        self._sr: int = self._model.sr

    def synthesize(self, req: TTSRequest) -> bytes:
        if not req.text or not req.text.strip():
            raise TTSError("Text cannot be empty")
        try:
            import soundfile as sf

            wav = self._model.generate(
                req.text,
                temperature=req.temperature,
                top_p=req.top_p,
                top_k=req.top_k,
                repetition_penalty=req.repetition_penalty,
            )
            buf = io.BytesIO()
            sf.write(buf, wav[0].cpu().numpy(), self._sr, format="WAV", subtype="PCM_16")
            buf.seek(0)
            return buf.read()
        except Exception as e:
            raise TTSError(f"ChatterboxDirect synthesis failed: {e}") from e

    def close(self) -> None:
        pass


class ChatterboxServerBackend:
    """HTTP client backend for the chatterbox FastAPI server.

    Reuses tts_tools._get_retry_session() for consistent retry/backoff
    behaviour (3 retries, backoff_factor=1, status_forcelist=[429,5xx]).
    """

    def __init__(self, base_url: str = "http://localhost:8000") -> None:
        self._base_url = base_url.rstrip("/")
        self._session = _get_retry_session()

    def synthesize(self, req: TTSRequest) -> bytes:
        if not req.text or not req.text.strip():
            raise TTSError("Text cannot be empty")
        try:
            r = self._session.post(
                f"{self._base_url}/tts",
                json=req.as_dict(),
                timeout=120,
            )
            r.raise_for_status()
            return r.content
        except requests.exceptions.RequestException as e:
            raise TTSError(f"ChatterboxServer request failed: {e}") from e

    def close(self) -> None:
        self._session.close()
