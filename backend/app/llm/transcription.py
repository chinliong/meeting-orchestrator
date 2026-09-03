"""Speech-to-text layer (Objective 4).

Three backends, tried in order, each falling through to the next on failure:

1. **Deepgram Nova-3** (preferred). The most accurate option measured: 13.0% and 15.3% word
   error rate on the two AMI reference meetings, against 16.6% and 17.2% for hosted Whisper -
   a gap the bootstrap separates on both. Its advantage is almost entirely fewer deletions
   (181 against 269 on ES2008a), i.e. it drops less overlapping speech. See
   docs/asr-evaluation.md.

2. **Hosted Whisper API** (fallback). An OpenAI-compatible endpoint - Groq by default. Slightly
   less accurate but its free tier resets daily, where Deepgram's is a one-off credit, so this
   is what keeps the app working once that credit is exhausted.

3. **Local Whisper model** (dev only). Needs `pip install -r requirements-audio.txt` (PyTorch +
   ffmpeg) and roughly 1.5 GB of RAM, which a free-tier host does not have.

Backends 1 and 2 run no model locally, which is what makes the audio path deployable on a
memory-constrained host. If none is available the endpoint returns a clear 503 rather than
crashing.

Environment variables:
    DEEPGRAM_API_KEY         API key for Deepgram (enables backend #1).
    DEEPGRAM_MODEL           Deepgram model. Default "nova-3".
    TRANSCRIPTION_API_KEY    API key for the hosted Whisper endpoint (enables backend #2).
    TRANSCRIPTION_BASE_URL   Override the API base URL. Unset = OpenAI. Groq example:
                             https://api.groq.com/openai/v1
    TRANSCRIPTION_MODEL      Model name. Default "whisper-1" (OpenAI);
                             Groq: "whisper-large-v3-turbo".
    WHISPER_MODEL_SIZE       Local model size for backend #3 (default "turbo").
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

# Local-model size (backend #2, dev only). "turbo" measured 17.5% word error rate against
# 28.8% for "base" on the AMI reference recording. Avoid "large-v3": at library defaults it
# hallucinates on meeting audio and scores 33.1%, though the same weights reach 16.4% behind a
# hosted endpoint that adds voice-activity detection - see docs/asr-evaluation.md.
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "turbo")


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


def _deepgram_key() -> str | None:
    return os.getenv("DEEPGRAM_API_KEY") or None


def _local_whisper_installed() -> bool:
    try:
        import whisper  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def is_available() -> bool:
    """True if any backend is configured: a hosted key, or the local Whisper package."""
    return (_deepgram_key() is not None or _api_key() is not None
            or _local_whisper_installed())


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


# Deepgram accepts raw bytes with a content type; these cover what _compress_for_api emits
# plus the originals we might forward when ffmpeg is unavailable.
_DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
_MIME = {".flac": "audio/flac", ".ogg": "audio/ogg", ".wav": "audio/wav",
         ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "video/mp4",
         ".webm": "audio/webm"}


def _transcribe_via_deepgram(tmp_path: str) -> str:
    """Backend #1: Deepgram, one synchronous POST of the compressed audio.

    Reuses the same compression as the Whisper path so both backends see identical audio and
    the endpoint stays within a sane upload size.
    """
    import httpx

    compressed = _compress_for_api(tmp_path)
    upload_path = compressed or tmp_path
    model = os.getenv("DEEPGRAM_MODEL", "nova-3")
    started = time.perf_counter()
    try:
        with open(upload_path, "rb") as audio:
            resp = httpx.post(
                _DEEPGRAM_URL,
                params={"model": model, "smart_format": "true"},
                headers={"Authorization": f"Token {_deepgram_key()}",
                         "Content-Type": _MIME.get(os.path.splitext(upload_path)[1],
                                                   "application/octet-stream")},
                content=audio.read(), timeout=300)
        if resp.status_code != 200:
            raise TranscriptionError(
                f"Deepgram rejected the request (HTTP {resp.status_code}).")
        log.info("transcription: deepgram %s %.1fs", model, time.perf_counter() - started)
        alt = resp.json()["results"]["channels"][0]["alternatives"][0]
    except httpx.HTTPError as exc:
        raise TranscriptionError(f"Could not reach Deepgram: {exc}") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise TranscriptionError("Deepgram returned an unexpected response.") from exc
    finally:
        if compressed:
            os.unlink(compressed)
    return alt["transcript"].strip()


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

    Tries each configured backend in accuracy order and falls through on failure, so an
    exhausted Deepgram credit or a provider outage degrades to a slightly less accurate
    transcript instead of an error. Each backend is attempted once: a retry chain is what made
    an earlier provider time out the whole request rather than fail over.
    """
    if not is_available():
        raise WhisperUnavailableError(
            "Audio transcription is not configured. Set DEEPGRAM_API_KEY or "
            "TRANSCRIPTION_API_KEY to use a hosted service, or run "
            "`pip install -r requirements-audio.txt` for local Whisper."
        )

    backends = []
    if _deepgram_key() is not None:
        backends.append(("deepgram", _transcribe_via_deepgram))
    if _api_key() is not None:
        backends.append(("hosted whisper", _transcribe_via_api))
    if _local_whisper_installed():
        backends.append(("local whisper", _transcribe_locally))

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        last: Exception | None = None
        for name, call in backends:
            try:
                return call(tmp_path)
            except (TranscriptionError, WhisperUnavailableError) as exc:
                log.warning("transcription: %s failed (%s)", name, exc)
                last = exc
        raise last if last else WhisperUnavailableError(
            "Audio transcription is not configured.")
    finally:
        os.unlink(tmp_path)
