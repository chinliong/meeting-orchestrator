"""Run every browser suite against the fake backend (e2e/fake_backend.py), so nothing is charged.

The frontend must already be running at E2E_APP_URL (default http://localhost:3000) and talking
to http://localhost:8000 or 127.0.0.1:8000: `npm run dev` in frontend/, or a static build served
as CI does. Port 8000 must be free, so stop a local dev backend first.

    pip install -r e2e/requirements.txt && python -m playwright install chromium
    python e2e/run.py              # every suite
    python e2e/run.py board        # only the named suites

Each suite starts from a fresh database. Exits non-zero if any check fails.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"
API = "http://127.0.0.1:8000/api/v1"

# Suite -> rate limits it runs with. The others run with limits off, since together they sign in and
# parse more often than the real limits allow; rate_limits uses low ones so it can reach them.
SUITES = {
    "board": None,
    "summaries": None,
    "passwords": None,
    "export": None,
    "account_long_list": None,
    "rate_limits": {"RATE_LIMIT_PARSE": "2/hour", "RATE_LIMIT_LOGIN": "3/minute", "RATE_LIMIT_AI": "3/hour"},
}


def api(method: str, path: str, body=None, token=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_backend(db_path: Path, limits: dict | None) -> subprocess.Popen:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path}"}
    env.update(limits or {"RATE_LIMITS_ENABLED": "false"})
    proc = subprocess.Popen([sys.executable, str(HERE / "fake_backend.py")], env=env)
    end = time.time() + 30
    while time.time() < end:
        try:
            api("GET", "/health")
            return proc
        except OSError:
            time.sleep(0.3)
    proc.kill()
    sys.exit("The fake backend did not start.")


def seed(db_path: Path) -> None:
    """The demo account and its sample board (app.seed), and an account with 100 boards."""
    subprocess.run([sys.executable, "-m", "app.seed"], cwd=BACKEND, check=True, stdout=subprocess.DEVNULL,
                   env={**os.environ, "DATABASE_URL": f"sqlite:///{db_path}"})
    token = api("POST", "/auth/signup", {"email": "many@example.com", "password": "many12345"})["token"]
    api("PATCH", "/auth/notifications", {"notify_email": True, "notify_days_before": 2}, token)
    names = [f"Payroll workstream {i}" for i in range(10)] + [f"Programme board {i:02d}" for i in range(90)]
    ids = [api("POST", "/projects", {"name": n, "description": ""}, token)["id"] for n in names]
    for project_id in ids[40:43]:  # three boards with reminders on, listed first in Account settings
        api("PATCH", f"/projects/{project_id}", {"notify_enabled": True}, token)


def main() -> int:
    chosen = sys.argv[1:] or list(SUITES)
    unknown = [s for s in chosen if s not in SUITES]
    if unknown:
        sys.exit(f"Unknown suite(s): {', '.join(unknown)}. Choose from: {', '.join(SUITES)}")
    if port_in_use(8000):
        sys.exit("Port 8000 is in use. Stop the dev backend first; the suites need the fake one there.")

    failed = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, name in enumerate(chosen):
            db_path = Path(tmp) / f"e2e-{i}.db"
            backend = start_backend(db_path, SUITES[name])
            try:
                seed(db_path)
                print(f"\n=== {name}", flush=True)
                if subprocess.run([sys.executable, str(HERE / f"{name}.py")]).returncode != 0:
                    failed.append(name)
            finally:
                backend.terminate()
                backend.wait(timeout=10)
    print("\nAll suites passed." if not failed else f"\nFailed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
