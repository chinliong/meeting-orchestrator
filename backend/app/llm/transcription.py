"""Speech-to-text layer (Objective 4).

Two interchangeable backends, selected automatically:

1. **Hosted Whisper API** (default in the cloud). If TRANSCRIPTION_API_KEY is set, audio is
   sent to an OpenAI-compatible transcription endpoint. This works on memory-constrained
   hosts (e.g. Render free tier) because no model runs locally. It targets OpenAI's Whisper
   by default, and Groq's OpenAI-compatible Whisper endpoint by setting TRANSCRIPTION_BASE_URL.

2. **Local Whisper model** (dev convenience). If no API key is set but the `openai-whisper`
   package is installed (`pip install -r requirements-audio.txt`, pulls in PyTorch + needs
   ffmpeg), transcription runs locally on CPU.

If neither is available the audio endpoint returns a clear 503 rather than crashing.

Environment variables:
    TRANSCRIPTION_API_KEY    API key for the hosted endpoint (enables backend #1).
    TRANSCRIPTION_BASE_URL   Override the API base URL. Unset = OpenAI. Groq example:
                             https://api.groq.com/openai/v1
    TRANSCRIPTION_MODEL      Model name. Default "whisper-1" (OpenAI); Groq: "whisper-large-v3".
    WHISPER_MODEL_SIZE       Local model size for backend #2 (default "base").
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
from functools import lru_cache

# uvicorn configures this logger at INFO, so these lines show up in the Render logs.
log = logging.getLogger("uvicorn.error")

# Local-model size (backend #2); "base" is a good accuracy/speed trade-off on CPU.
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")


class WhisperUnavailableError(RuntimeError):
    """Raised when audio transcription is requested but no backend is configured."""


class TranscriptionError(RuntimeError):
    """Raised when a configured backend fails (e.g. upstream API error, file too large).

    Distinct from WhisperUnavailableError: the backend exists but the request failed. The
    endpoint surfaces this as a normal HTTP error (with CORS headers) instead of letting it
    bubble up as an unhandled 500, which would reach the browser as an opaque "Failed to fetch".
    """


def _api_key() -> str | None:
    return os.getenv("TRANSCRIPTION_API_KEY") or None


def _local_whisper_installed() -> bool:
    try:
        import whisper  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def is_available() -> bool:
    """True if either a hosted API key is set or the local Whisper package is importable."""
    return _api_key() is not None or _local_whisper_installed()


# Stay under the hosted API's upload cap (Groq free tier is ~25 MB) with margin.
_MAX_UPLOAD_BYTES = 24 * 1024 * 1024

# Mono 16 kHz is what Whisper consumes anyway; -vn drops any video track.
_BASE_FFMPEG_ARGS = ["-vn", "-ac", "1", "-ar", "16000"]
# FLAC has no psychoacoustic model, so it encodes ~4x cheaper on CPU than Opus — the encode
# dominates transcode time on Render's throttled free core. It's larger than Opus but stays
# under the cap for typical recordings (~38 min); longer audio falls back to Opus below.
_FLAC_ARGS = ["-c:a", "flac"]
# Opus 16 kbps is tiny (covers hours) but CPU-heavy to encode; used only as the size fallback.
_OPUS_ARGS = ["-c:a", "libopus", "-b:a", "16k", "-application", "voip", "-compression_level", "0"]


def _run_ffmpeg(src_path: str, codec_args: list[str], suffix: str) -> str:
    """Transcode src_path with the given codec args. Returns a temp path the caller deletes."""
    out = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    out.close()
    started = time.perf_counter()
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", src_path, *_BASE_FFMPEG_ARGS, *codec_args, out.name],
        capture_output=True,
    )
    if proc.returncode != 0:
        os.unlink(out.name)
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise TranscriptionError(f"Could not process the audio/video file: {detail[0]}")
    log.info(
        "transcription: ffmpeg %s %.1fs (%d -> %d bytes)",
        codec_args[1], time.perf_counter() - started,
        os.path.getsize(src_path), os.path.getsize(out.name),
    )
    return out.name


def _compress_for_api(src_path: str) -> str | None:
    """Transcode audio/video to a compact file the hosted Whisper endpoint will accept.

    Prefers FLAC because it encodes far cheaper on a weak CPU; if the result would exceed the
    upload cap (very long recordings), re-encodes to the much smaller Opus instead.

    Returns a temp file path (the caller deletes it), or None when ffmpeg is unavailable
    (e.g. local dev) so the caller can fall back to uploading the original.
    """
    if not shutil.which("ffmpeg"):
        return None
    flac = _run_ffmpeg(src_path, _FLAC_ARGS, ".flac")
    if os.path.getsize(flac) <= _MAX_UPLOAD_BYTES:
        return flac
    os.unlink(flac)  # too long for FLAC to fit — fall back to Opus
    return _run_ffmpeg(src_path, _OPUS_ARGS, ".ogg")


def _transcribe_via_api(tmp_path: str) -> str:
    """Backend #1: OpenAI-compatible hosted transcription endpoint."""
    import openai  # lightweight; part of core requirements
    from openai import OpenAI

    compressed = _compress_for_api(tmp_path)
    upload_path = compressed or tmp_path
    client = OpenAI(api_key=_api_key(), base_url=os.getenv("TRANSCRIPTION_BASE_URL") or None)
    model = os.getenv("TRANSCRIPTION_MODEL", "whisper-1")
    started = time.perf_counter()
    try:
        with open(upload_path, "rb") as audio:
            result = client.audio.transcriptions.create(model=model, file=audio)
        log.info("transcription: %s API call %.1fs", model, time.perf_counter() - started)
    except openai.APIStatusError as exc:
        if exc.status_code == 413:
            raise TranscriptionError(
                "The audio/video file is too large for the transcription service even after "
                "compression. Please upload a shorter recording."
            ) from exc
        raise TranscriptionError(
            f"The transcription service rejected the request (HTTP {exc.status_code})."
        ) from exc
    except openai.APIError as exc:  # network/timeout/connection issues
        raise TranscriptionError(f"Could not reach the transcription service: {exc}") from exc
    finally:
        if compressed:
            os.unlink(compressed)
    return result.text.strip()


@lru_cache(maxsize=1)
def _load_local_model():
    """Backend #2: load the local Whisper model once."""
    try:
        import whisper  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise WhisperUnavailableError(
            "Local Whisper is not installed. Either set TRANSCRIPTION_API_KEY to use a hosted "
            "Whisper API, or run `pip install -r requirements-audio.txt`."
        ) from exc
    return whisper.load_model(WHISPER_MODEL_SIZE)


def _transcribe_locally(tmp_path: str) -> str:
    return _load_local_model().transcribe(tmp_path)["text"].strip()


def transcribe_audio(data: bytes, suffix: str = ".wav") -> str:
    """Transcribe raw audio/video bytes into text.

    Prefers the hosted API when TRANSCRIPTION_API_KEY is set; otherwise falls back to a
    local Whisper model. Both read from a file path, so the upload is written to a temp
    file that is cleaned up afterwards.
    """
    if not is_available():
        raise WhisperUnavailableError(
            "Audio transcription is not configured. Set TRANSCRIPTION_API_KEY to use a hosted "
            "Whisper API, or run `pip install -r requirements-audio.txt` for local Whisper."
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        if _api_key() is not None:
            return _transcribe_via_api(tmp_path)
        return _transcribe_locally(tmp_path)
    finally:
        os.unlink(tmp_path)
