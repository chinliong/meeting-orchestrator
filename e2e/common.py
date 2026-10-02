"""Shared setup for the browser suites in this folder; e2e/run.py runs them all."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import wave
from pathlib import Path

APP_URL = os.getenv("E2E_APP_URL", "http://localhost:3000").rstrip("/") + "/app"
API_URL = os.getenv("E2E_API_URL", "http://127.0.0.1:8000/api/v1")
# Screenshots are kept for looking into a failure; nothing is compared against them.
OUT = Path(os.getenv("E2E_OUT", str(Path(tempfile.gettempdir()) / "meeting-orchestrator-e2e")))
OUT.mkdir(parents=True, exist_ok=True)

_results: list[bool] = []


def check(name: str, ok: object, detail: str = "") -> None:
    _results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def finish() -> None:
    """Print the tally and exit non-zero if any check failed (or none ran)."""
    passed = sum(_results)
    print(f"\n{passed}/{len(_results)} passed", flush=True)
    sys.exit(0 if _results and passed == len(_results) else 1)


def wait_until(condition, timeout: float = 15, step: float = 0.2) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        time.sleep(step)
    return False


def silent_wav() -> str:
    """A one-second silent recording; the fake backend's transcription ignores the audio."""
    path = OUT / "silence.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\0\0" * 8000)
    return str(path)
