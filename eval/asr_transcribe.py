"""Produce a cached transcript from a hosted speech-to-text endpoint (Objective 4).

Runs the audio through the application's own transcription path - the same compression and
upload code the deployed backend uses - so the measured accuracy and wall-clock reflect what a
user actually gets, not a separate research harness.

    python -m eval.asr_transcribe groq-turbo

Writes eval/asr_transcripts/ES2008a.<key>.txt and a .timing.json sidecar that eval.asr_eval
reads, so scoring stays offline and repeatable.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
AUDIO_DIR = REPO / "data" / "test-audio"
TRANSCRIPTS = REPO / "eval" / "asr_transcripts"


def find_audio(meeting: str) -> Path:
    """The recording for a meeting, whichever container it was published in."""
    for name in (f"{meeting}.Mix-Headset.wav", f"{meeting}.mp4", f"{meeting}.wav"):
        if (AUDIO_DIR / name).exists():
            return AUDIO_DIR / name
    raise SystemExit(f"No audio for {meeting} in {AUDIO_DIR}")

sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

# Hosted OpenAI-compatible endpoints. Each entry is (base_url, model, env var holding the key).
# The app reaches these through TRANSCRIPTION_BASE_URL/TRANSCRIPTION_MODEL, so anything runnable
# here is deployable by setting three environment variables - no code change.
HOSTED = {
    "groq-turbo":    ("https://api.groq.com/openai/v1", "whisper-large-v3-turbo", "GROQ_API_KEY"),
    "groq-large-v3": ("https://api.groq.com/openai/v1", "whisper-large-v3", "GROQ_API_KEY"),
    "openai":        (None, "whisper-1", "OPENAI_API_KEY"),
}

# Local Whisper sizes, run through the same entry point with the hosted backend disabled.
# Named "local-<size>" so a transcript file always says which deployment produced it.
LOCAL = ["turbo", "base", "small", "medium", "large-v3"]

# AssemblyAI is not OpenAI-compatible, so it gets its own client below. It is the competing
# architecture in the evaluation: a different vendor's model, hosted like Groq, which keeps the
# comparison to the one variable that matters - the model - with no hardware or network
# difference to confound it.
ASSEMBLYAI = {
    "assemblyai-universal-3-5-pro": "universal-3-5-pro",
    "assemblyai-universal-2": "universal-2",
}
ASSEMBLYAI_ROOT = "https://api.assemblyai.com/v2"

# Deepgram, the second competing architecture. Synchronous like Groq, so unlike AssemblyAI its
# wall-clock is directly comparable rather than including queue time.
DEEPGRAM = {
    "deepgram-nova-3": "nova-3",
    "deepgram-nova-2": "nova-2",
}
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
_MIME = {".flac": "audio/flac", ".wav": "audio/wav", ".mp4": "video/mp4", ".ogg": "audio/ogg"}


def transcribe_assemblyai(path: str, model: str, key: str, poll: float = 3.0) -> str:
    """Upload, submit, then poll until the transcript is ready.

    AssemblyAI is asynchronous: the wall-clock therefore includes queue time and is not a
    like-for-like latency measurement against a synchronous endpoint. The transcript it returns
    is directly comparable; the timing is not.
    """
    import httpx

    headers = {"authorization": key}
    with httpx.Client(timeout=600) as http:
        with open(path, "rb") as fh:
            up = http.post(f"{ASSEMBLYAI_ROOT}/upload", headers=headers, content=fh.read())
        up.raise_for_status()

        job = http.post(f"{ASSEMBLYAI_ROOT}/transcript", headers=headers,
                        json={"audio_url": up.json()["upload_url"], "speech_model": model})
        job.raise_for_status()
        tid = job.json()["id"]

        while True:
            r = http.get(f"{ASSEMBLYAI_ROOT}/transcript/{tid}", headers=headers)
            r.raise_for_status()
            body = r.json()
            if body["status"] == "completed":
                return (body["text"] or "").strip()
            if body["status"] == "error":
                raise SystemExit(f"AssemblyAI failed: {body.get('error')}")
            time.sleep(poll)


def transcribe_deepgram(path: str, model: str, key: str) -> str:
    """One synchronous POST of the raw bytes; the transcript comes back in the response."""
    import httpx

    with open(path, "rb") as fh:
        audio = fh.read()
    r = httpx.post(
        DEEPGRAM_URL,
        params={"model": model, "smart_format": "true"},
        headers={"Authorization": f"Token {key}",
                 "Content-Type": _MIME.get(Path(path).suffix, "application/octet-stream")},
        content=audio, timeout=600)
    if r.status_code != 200:
        raise SystemExit(f"Deepgram failed ({r.status_code}): {r.text[:300]}")
    return r.json()["results"]["channels"][0]["alternatives"][0]["transcript"].strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe the reference recording via a hosted API.")
    ap.add_argument("backend",
                    choices=sorted(HOSTED) + sorted(ASSEMBLYAI) + sorted(DEEPGRAM)
                    + [f"local-{m}" for m in LOCAL],
                    help="configuration to run")
    ap.add_argument("--raw", action="store_true",
                    help="send the original file instead of the 16 kHz mono FLAC the app "
                         "produces; use it to check that the app's preprocessing is not itself "
                         "costing a competitor accuracy")
    ap.add_argument("--meeting", default="ES2008a", help="meeting id (default ES2008a)")
    ap.add_argument("--repeat", type=int, default=1,
                    help="call the endpoint N times and record the median wall-clock; a single "
                         "call is one sample of a network round trip, not a stable measurement")
    args = ap.parse_args()

    if args.backend in ASSEMBLYAI:
        base_url, model = ASSEMBLYAI_ROOT, ASSEMBLYAI[args.backend]
        key = os.getenv("ASSEMBLYAI_API_KEY")
        if not key:
            sys.exit("Set ASSEMBLYAI_API_KEY in backend/.env (or export it) before running.")
    elif args.backend in DEEPGRAM:
        base_url, model = DEEPGRAM_URL, DEEPGRAM[args.backend]
        key = os.getenv("DEEPGRAM_API_KEY")
        if not key:
            sys.exit("Set DEEPGRAM_API_KEY in backend/.env (or export it) before running.")
    elif args.backend.startswith("local-"):
        # Clearing the key makes transcribe_audio take its local-model branch.
        base_url, model = None, args.backend[len("local-"):]
        os.environ.pop("TRANSCRIPTION_API_KEY", None)
        os.environ["WHISPER_MODEL_SIZE"] = model
    else:
        base_url, model, key_var = HOSTED[args.backend]
        key = os.getenv(key_var) or os.getenv("TRANSCRIPTION_API_KEY")
        if not key:
            sys.exit(f"Set {key_var} in backend/.env (or export it) before running.")
        os.environ["TRANSCRIPTION_API_KEY"] = key
        os.environ["TRANSCRIPTION_MODEL"] = model
        if base_url:
            os.environ["TRANSCRIPTION_BASE_URL"] = base_url
        else:
            os.environ.pop("TRANSCRIPTION_BASE_URL", None)

    # Imported after the environment is set, and reused rather than reimplemented so every
    # configuration receives byte-identical audio - the comparison is of models, not of
    # preprocessing.
    from app.llm.transcription import _compress_for_api, transcribe_audio  # noqa: E402

    audio = find_audio(args.meeting)
    where = base_url or ("local CPU" if args.backend.startswith("local-") else "OpenAI")
    print(f"{args.meeting} ({audio.name}) -> {args.backend}: {model} via {where}"
          f"{' [raw audio]' if args.raw else ''}")

    runs = []
    if args.backend in ASSEMBLYAI or args.backend in DEEPGRAM:
        call = transcribe_assemblyai if args.backend in ASSEMBLYAI else transcribe_deepgram
        upload = None if args.raw else _compress_for_api(str(audio))
        try:
            for i in range(args.repeat):
                started = time.perf_counter()
                text = call(upload or str(audio), model, key)
                runs.append(round(time.perf_counter() - started, 2))
                print(f"  run {i + 1}: {runs[-1]:.2f}s ({len(text.split())} words)")
        finally:
            if upload:
                os.unlink(upload)
    else:
        data = audio.read_bytes()
        for i in range(args.repeat):
            started = time.perf_counter()
            text = transcribe_audio(data, suffix=audio.suffix)
            runs.append(round(time.perf_counter() - started, 2))
            print(f"  run {i + 1}: {runs[-1]:.2f}s ({len(text.split())} words)")
    elapsed = statistics.median(runs)

    TRANSCRIPTS.mkdir(exist_ok=True)
    suffix = f"{args.backend}-raw" if args.raw else args.backend
    (TRANSCRIPTS / f"{args.meeting}.{suffix}.txt").write_text(text + "\n")
    (TRANSCRIPTS / f"{args.meeting}.{suffix}.timing.json").write_text(
        json.dumps({"seconds": elapsed, "runs": runs, "model": model,
                    "base_url": base_url or ("local" if args.backend.startswith("local-")
                                             else "https://api.openai.com/v1")},
                   indent=2) + "\n")
    print(f"median {elapsed:.2f}s over {len(runs)} run(s) -> "
          f"eval/asr_transcripts/{args.meeting}.{suffix}.txt")
    print("now run: python -m eval.asr_eval")


if __name__ == "__main__":
    main()
