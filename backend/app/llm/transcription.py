"""Optional speech-to-text layer using OpenAI Whisper (run locally).

Whisper (and its heavy PyTorch dependency) is intentionally *not* part of the core
requirements. Install it with:

    pip install -r requirements-audio.txt

The import is lazy so the rest of the backend runs even when Whisper is absent; the
audio endpoint then returns a clear 503 instead of crashing on startup.
"""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache

# Model size is configurable; "base" is a good accuracy/speed trade-off on CPU.
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")


class WhisperUnavailableError(RuntimeError):
    """Raised when audio transcription is requested but Whisper isn't installed."""


@lru_cache(maxsize=1)
def _load_model():
    try:
        import whisper  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise WhisperUnavailableError(
            "openai-whisper is not installed. Run `pip install -r requirements-audio.txt` "
            "to enable audio/video transcription."
        ) from exc
    return whisper.load_model(WHISPER_MODEL_SIZE)


def is_available() -> bool:
    """True if the openai-whisper package can be imported."""
    try:
        import whisper  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def transcribe_audio(data: bytes, suffix: str = ".wav") -> str:
    """Transcribe raw audio/video bytes into text.

    Whisper reads from a file path (it shells out to ffmpeg), so the upload is written
    to a temporary file that is cleaned up afterwards.
    """
    model = _load_model()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        result = model.transcribe(tmp_path)
        return result["text"].strip()
    finally:
        os.unlink(tmp_path)
