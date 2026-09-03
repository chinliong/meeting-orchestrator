"""Speech-to-text layer (Objective 4).

Three interchangeable backends, tried in order:

1. **Gemini** (default in the cloud). If GEMINI_API_KEY is set, the recording is sent to a
   chain of Gemini models. Chosen on measured word error rate against the AMI corpus - see
   docs/asr-evaluation.md - where Gemini scored 10.9-12.1% against 17.5% for the best local
   Whisper model and 28.8% for the previous default. The chain exists because each model
   carries its own small free daily allowance, so exhausting one need not disable the feature.

2. **Hosted Whisper API**. If TRANSCRIPTION_API_KEY is set, audio is sent to an
   OpenAI-compatible transcription endpoint (OpenAI by default, or Groq via
   TRANSCRIPTION_BASE_URL).

3. **Local Whisper model** (offline fallback). If neither key is set but `openai-whisper` is
   installed (`pip install -r requirements-audio.txt`, pulls in PyTorch + needs ffmpeg),
   transcription runs locally on CPU. No key, no network and no quota, at roughly 5 points
   more word error rate than Gemini.

If none is available the audio endpoint returns a clear 503 rather than crashing.

Environment variables:
    GEMINI_API_KEY           API key for backend #1.
    GEMINI_TRANSCRIBE_MODELS Comma-separated model chain. Default is the measured order.
    TRANSCRIPTION_API_KEY    API key for the hosted Whisper endpoint (enables backend #2).
    TRANSCRIPTION_BASE_URL   Override the API base URL. Unset = OpenAI. Groq example:
                             https://api.groq.com/openai/v1
    TRANSCRIPTION_MODEL      Model name. Default "whisper-1" (OpenAI); Groq: "whisper-large-v3".
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

# Local-model size (backend #3). "turbo" measured 17.5% word error rate against
# 28.8% for "base" on the same recording, for ~3 extra minutes of CPU per meeting.
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


def _local_whisper_installed() -> bool:
    try:
        import whisper  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def _gemini_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or None


def _gemini_models() -> list[str]:
    """The model chain, best-measured first.

    Ordered by the speed/accuracy frontier in docs/asr-evaluation.md: 3.7 Flash is the fastest
    backend under 13% word error rate, 3.6 Flash is the most accurate. 3.8 Flash trails both and
    prefaces its output with commentary (see _strip_preamble), so it serves last and only after
    the other two have exhausted their daily allowances.
    """
    raw = os.getenv("GEMINI_TRANSCRIBE_MODELS",
                    "gemini-3.7-flash,gemini-3.6-flash,gemini-3.8-flash")
    return [m.strip() for m in raw.split(",") if m.strip()]


def is_available() -> bool:
    """True if any backend can run: a Gemini key, a hosted Whisper key, or local Whisper."""
    return (_gemini_key() is not None or _api_key() is not None
            or _local_whisper_installed())


# Stay under the hosted API's upload cap (Groq free tier is ~25 MB) with margin.
_MAX_UPLOAD_BYTES = 24 * 1024 * 1024

# Mono 16 kHz is what Whisper consumes anyway; -vn drops any video track.
_BASE_FFMPEG_ARGS = ["-vn", "-ac", "1", "-ar", "16000"]
# FLAC has no psychoacoustic model, so it encodes ~4x cheaper on CPU than Opus — the encode
# dominates transcode time on Render's throttled free core. It's larger than Opus but stays
# under the cap for typical recordings (~38 min); longer audio falls back to Opus below.
_FLAC_ARGS = ["-c:a", "flac"]
# Gemini takes the audio inline as base64, which inflates it ~33%, so this targets a small
# file rather than a cheap encode: 32 kbps mono is ~4 MB for a 17-minute meeting.
_MP3_ARGS = ["-c:a", "libmp3lame", "-b:a", "32k"]
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


# Gemini's inline-data request cap; base64 expands the payload by about a third.
_GEMINI_MAX_AUDIO_BYTES = 14 * 1024 * 1024
_GEMINI_PROMPT = (
    "Transcribe this meeting recording verbatim in English. Output only the transcript text, "
    "with no speaker labels, timestamps, commentary or headings. Include every spoken word, "
    "including filler words such as um and uh."
)


def _strip_preamble(text: str) -> str:
    """Drop a leading block where the model narrates the task instead of transcribing it.

    Gemini 3.8 Flash reliably prefaces its transcript by restating the audio duration and
    quoting the prompt back, even with thinking disabled. Left in place that preamble would be
    parsed as meeting content and could surface as a spurious action item, so it is removed
    rather than trusted. Models that comply are unaffected: nothing matches.
    """
    markers = ("follow instructions:", "the audio is around", "the audio is approximately",
               "here is the transcript", "transcript:")
    lines = text.split("\n")
    while lines and (not lines[0].strip()
                     or any(m in lines[0].lower()[:120] for m in markers)):
        lines.pop(0)
    return "\n".join(lines).strip()


def _transcribe_via_gemini(tmp_path: str) -> str:
    """Backend #1: Gemini, trying each model in the chain until one answers.

    Two upstream failures are handled differently because they mean different things. A 429 is
    the daily allowance for that model being spent, so the chain advances immediately and does
    not come back to it. A 503 is transient capacity pressure, which retries on the same model
    first - in testing it usually succeeded on the second attempt.
    """
    import base64
    import json as _json
    import urllib.error
    import urllib.request

    compressed = _run_ffmpeg(tmp_path, _MP3_ARGS, ".mp3") if shutil.which("ffmpeg") else None
    upload_path = compressed or tmp_path
    try:
        size = os.path.getsize(upload_path)
        if size > _GEMINI_MAX_AUDIO_BYTES:
            raise TranscriptionError(
                "The recording is too long for the transcription service. Please upload a "
                "shorter recording."
            )
        audio_b64 = base64.b64encode(open(upload_path, "rb").read()).decode()
    finally:
        if compressed:
            os.unlink(compressed)

    body = {
        "contents": [{"role": "user", "parts": [
            {"text": _GEMINI_PROMPT},
            {"inline_data": {"mime_type": "audio/mp3" if compressed else "audio/wav",
                             "data": audio_b64}}]}],
        # temperature 0: a transcript should not vary between identical requests.
        "generationConfig": {"maxOutputTokens": 32768, "temperature": 0},
    }
    payload = _json.dumps(body).encode()
    last = "no Gemini model answered"
    for model in _gemini_models():
        for attempt in range(3):
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{model}:generateContent?key={_gemini_key()}")
            req = urllib.request.Request(url, payload, {"Content-Type": "application/json"})
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    data = _json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code} from {model}"
                if exc.code == 429:            # daily allowance spent - move on, do not retry
                    log.info("transcription: %s quota exhausted, trying next model", model)
                    break
                log.info("transcription: %s HTTP %d (attempt %d)", model, exc.code, attempt + 1)
                time.sleep(2 * (attempt + 1))
                continue
            except urllib.error.URLError as exc:
                last = f"could not reach Gemini: {exc.reason}"
                time.sleep(2 * (attempt + 1))
                continue
            candidates = data.get("candidates") or []
            text = "".join(
                part.get("text", "")
                for part in (candidates[0].get("content", {}).get("parts") or [])
            ) if candidates else ""
            text = _strip_preamble(text)
            if not text:
                last = f"{model} returned no transcript"
                break
            # Which model served the request is logged: the chain means it varies between
            # uploads, and a transcript that cannot be attributed cannot be explained later.
            log.info("transcription: %s %.1fs (%d chars)",
                     model, time.perf_counter() - started, len(text))
            return text
    raise TranscriptionError(f"Transcription failed: {last}.")


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

    Prefers Gemini, then a hosted Whisper endpoint, then the local model, in descending order
    of measured accuracy. Every backend reads from a file path, so the upload is written to a
    temp file that is cleaned up afterwards.

    If Gemini is configured but every model in its chain fails, this falls through to whatever
    else is available rather than failing the upload: a transcript at 17.5% word error rate is
    worth more to the user than an error page.
    """
    if not is_available():
        raise WhisperUnavailableError(
            "Audio transcription is not configured. Set GEMINI_API_KEY, or TRANSCRIPTION_API_KEY "
            "for a hosted Whisper API, or run `pip install -r requirements-audio.txt` for local "
            "Whisper."
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        if _gemini_key() is not None:
            try:
                return _transcribe_via_gemini(tmp_path)
            except TranscriptionError:
                if _api_key() is None and not _local_whisper_installed():
                    raise
                log.warning("transcription: Gemini chain failed, falling back")
        if _api_key() is not None:
            return _transcribe_via_api(tmp_path)
        return _transcribe_locally(tmp_path)
    finally:
        os.unlink(tmp_path)
