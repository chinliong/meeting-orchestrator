"""Seed the database with a demo account, sample projects and pre-extracted tasks.

This is deterministic and offline — it does NOT call the LLM, so the dashboard has
realistic data across all three Kanban columns on first run without spending API calls.
It also adds two demo boards captured from the app's own model output (app/demo_boards.json),
one with a pending meeting-assistant review. Boards that already exist are left alone.

Run with: python -m app.seed
"""
import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.auth import hash_password
from app.db import Base, SessionLocal, engine
from app.models.models import (
    AgentReview,
    Meeting,
    MeetingStatus,
    Project,
    Subtask,
    Task,
    TaskStatus,
    User,
)

# A demo account that owns the sample boards, so they're visible after a fresh seed.
DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo1234"

SAMPLE_PROJECTS = [
    (
        "SAP S/4HANA Go-Live Programme",
        "Cross-functional workshops tracking action items ahead of go-live.",
    ),
    (
        "Warehouse Management Rollout",
        "MM/WM logistics integration and warehouse readiness workstream.",
    ),
]

# (description, owner, deadline, status, confidence) for the first project's sample meeting.
SAMPLE_TASKS = [
    ("Finish the APAC cost center hierarchy mapping", "Daniel", date(2026, 6, 19), TaskStatus.IN_PROGRESS, 0.95),
    ("Confirm the new cost center codes", "Priya", date(2026, 6, 17), TaskStatus.DONE, 0.9),
    ("Loop in the banking team for next week's integration session", "Aisha", None, TaskStatus.TODO, 0.8),
    ("Review the open items report and flag duplicates before the dress rehearsal", "Priya", date(2026, 6, 18), TaskStatus.TODO, 0.85),
    ("Prepare the mitigating controls document for the external audit", "Daniel", date(2026, 6, 25), TaskStatus.TODO, 0.88),
]

# Demo boards built from real output of the app's models (see the file's note), so the demo account
# shows extraction, summaries, a subtask checklist and a pending assistant review without model calls.
DEMO_BOARDS = Path(__file__).with_name("demo_boards.json")


def _resolve(value, tasks, meetings):
    """Replace the fixture's {"task_ref": i} / {"meeting_ref": i} positions with the new rows' ids."""
    if isinstance(value, dict):
        if set(value) == {"task_ref"}:
            return tasks[value["task_ref"]].id
        if set(value) == {"meeting_ref"}:
            return meetings[value["meeting_ref"]].id
        return {k: _resolve(v, tasks, meetings) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, tasks, meetings) for v in value]
    return value


def seed_demo_boards(db, owner_id: int) -> list[str]:
    """Add each demo board the owner does not already have; returns the names added."""
    from app.api.agent import board_snapshot, fingerprint  # the review's baseline, as the app computes it

    added = []
    for board in json.loads(DEMO_BOARDS.read_text())["boards"]:
        if db.query(Project).filter_by(name=board["name"], owner_user_id=owner_id).first():
            continue
        project = Project(name=board["name"], description=board["description"], owner_user_id=owner_id)
        db.add(project)
        db.flush()
        meetings = [Meeting(project_id=project.id, title=m["title"], transcript_text=m["transcript"],
                            meeting_date=date.fromisoformat(m["meeting_date"]), status=MeetingStatus.COMPLETE,
                            summary=m["summary"]) for m in board["meetings"]]
        db.add_all(meetings)
        db.flush()
        tasks = []
        for t in board["tasks"]:
            task = Task(project_id=project.id, meeting_id=meetings[t["meeting"]].id, description=t["description"],
                        owner=t["owner"], deadline=date.fromisoformat(t["deadline"]) if t["deadline"] else None,
                        status=TaskStatus(t["status"]), confidence=t["confidence"], source_decision=t["source_decision"])
            db.add(task)
            db.flush()
            db.add_all(Subtask(task_id=task.id, title=s["title"], done=s["done"], position=i)
                       for i, s in enumerate(t["subtasks"]))
            tasks.append(task)
        db.flush()
        if "pending_review" in board:
            review = board["pending_review"]
            db.add(AgentReview(id=str(uuid.uuid4()), project_id=project.id, status="draft",
                               expires_at=datetime.utcnow() + timedelta(hours=1),
                               input_json=json.dumps(review["input"]),
                               plan_json=json.dumps(_resolve(review["plan"], tasks, meetings)),
                               baseline_hash=fingerprint(board_snapshot(db, project.id))))
        added.append(board["name"])
    return added


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        demo = db.query(User).filter_by(email=DEMO_EMAIL).first()
        if demo is None:
            demo = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD))
            db.add(demo)
            db.flush()

        projects = {}
        for name, description in SAMPLE_PROJECTS:
            project = db.query(Project).filter_by(name=name).first()
            if project is None:
                project = Project(name=name, description=description, owner_user_id=demo.id)
                db.add(project)
                db.flush()
            elif project.owner_user_id is None:
                project.owner_user_id = demo.id
            projects[name] = project

        # Seed a completed sample meeting + tasks on the first project, only if it has none yet.
        first = projects["SAP S/4HANA Go-Live Programme"]
        if not db.query(Task).filter_by(project_id=first.id).first():
            meeting = Meeting(
                project_id=first.id,
                title="SAP FI/CO Finance Workshop #4 (sample)",
                transcript_text="(seeded sample meeting — tasks pre-extracted for the demo)",
                status=MeetingStatus.COMPLETE,
            )
            db.add(meeting)
            db.flush()
            for description, owner, deadline, status, confidence in SAMPLE_TASKS:
                db.add(
                    Task(
                        project_id=first.id,
                        meeting_id=meeting.id,
                        description=description,
                        owner=owner,
                        deadline=deadline,
                        status=status,
                        confidence=confidence,
                    )
                )

        added = seed_demo_boards(db, demo.id)
        db.commit()
        print("Seed complete." + (f" Added demo boards: {', '.join(added)}." if added else ""))
        print(f"Demo login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
