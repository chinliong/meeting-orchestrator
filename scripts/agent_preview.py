#!/usr/bin/env python3
"""Run the agent preview against an isolated SQLite database, using only the Gemini config.

From the repository root: backend/.venv/bin/python scripts/agent_preview.py
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from datetime import date

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local-agent"


def configure():
    LOCAL.mkdir(exist_ok=True)
    config = dotenv_values(ROOT / "backend/.env")
    # Read only these two values from the existing backend configuration. Never inherit its
    # database, auth secret or email providers, even when the .env points at production.
    key = os.getenv("GEMINI_API_KEY") or config.get("GEMINI_API_KEY") or ""
    model = os.getenv("GEMINI_MODEL") or config.get("GEMINI_MODEL") or ""
    secret_file = LOCAL / "auth-secret"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(48))
        secret_file.chmod(0o600)
    os.environ.update({
        "DATABASE_URL": f"sqlite:///{LOCAL / 'preview.db'}",
        "AUTH_SECRET": secret_file.read_text().strip(),
        "PYTHON_DOTENV_DISABLED": "1",
        "GEMINI_API_KEY": key, "GEMINI_MODEL": model,
        "LLM_PROVIDER": "gemini", "ENABLE_MEETING_AGENT": "true",
        "NEXT_PUBLIC_MEETING_AGENT_PREVIEW": "true",
        "NEXT_PUBLIC_API_BASE": "http://127.0.0.1:8100/api/v1",
        "CORS_ORIGINS": "http://127.0.0.1:3100,http://localhost:3100",
        "RATE_LIMITS_ENABLED": "true", "RENDER": "",
        "BREVO_API_KEY": "", "SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASSWORD": "",
        "CRON_SECRET": "", "ANTHROPIC_API_KEY": "", "DEEPGRAM_API_KEY": "",
        "NEXT_TELEMETRY_DISABLED": "1",
    })
    # An empty override must use the model defined by the existing Gemini client.
    if not model:
        os.environ.pop("GEMINI_MODEL", None)
    if not key:
        print("Gemini is not configured. Add GEMINI_API_KEY to backend/.env to run reviews.")
    sys.path.insert(0, str(ROOT / "backend"))


def seed_preview():
    from app.db import Base, SessionLocal, engine
    from app.models.models import Meeting, MeetingStatus, Project, Task, TaskStatus

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        project = db.query(Project).filter_by(name="Agent preview — website launch").first()
        if not project:
            project = Project(name="Agent preview — website launch",
                              description="Local sample board. Open the blue assistant button to ask questions or review a meeting.")
            db.add(project)
            db.flush()
            meeting = Meeting(project_id=project.id, title="Website launch planning",
                              meeting_date=date(2026, 10, 30), status=MeetingStatus.COMPLETE,
                              transcript_text="Alex: I will finish the landing page design by 4 November 2026. "
                              "Priya: I am working on the accessibility audit, due 3 November 2026. "
                              "Sam: The checkout integration and billing integration are separate tasks; "
                              "neither has started and we have not set dates for them.")
            db.add(meeting)
            db.flush()
            for description, owner, deadline, status in [
                ("Finish the landing page design", "Alex", date(2026, 11, 4), TaskStatus.IN_PROGRESS),
                ("Complete the accessibility audit", "Priya", date(2026, 11, 3), TaskStatus.IN_PROGRESS),
                ("Implement checkout integration", "Sam", None, TaskStatus.TODO),
                ("Implement billing integration", "Sam", None, TaskStatus.TODO),
            ]:
                db.add(Task(project_id=project.id, meeting_id=meeting.id, description=description,
                            owner=owner, deadline=deadline, status=status, confidence=1.0))
            db.commit()
        url = f"http://127.0.0.1:3100/app?w={project.edit_token}"
        (LOCAL / "preview-url.txt").write_text(url + "\n")
        return url


def main():
    configure()
    if "--backend" in sys.argv:
        import uvicorn
        uvicorn.run("app.main:app", host="127.0.0.1", port=8100)
        return
    # Refuse occupied ports rather than silently use the wrong app or API.
    for port in (3100, 8100):
        with socket.socket() as check:
            check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                check.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(f"Port {port} is in use. Stop the previous local preview first.")
    url = seed_preview()
    print(f"\nAgent preview: {url}\nDatabase: {LOCAL / 'preview.db'}\nPress Ctrl+C to stop.\n", flush=True)
    processes = []
    def stop(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        processes.append(subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--backend"], cwd=ROOT))
        processes.append(subprocess.Popen(["npm", "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3100"],
                                          cwd=ROOT / "frontend", start_new_session=True))
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in processes:
            if p.poll() is None:
                if p is processes[-1] and len(processes) > 1:
                    os.killpg(p.pid, signal.SIGTERM)
                else:
                    p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
