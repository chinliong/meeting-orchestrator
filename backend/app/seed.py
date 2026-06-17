"""Seed the database with sample projects, stakeholders, and pre-extracted tasks.

This is deterministic and offline — it does NOT call the LLM, so the dashboard has
realistic data across all three Kanban columns on first run without spending API calls.

Run with: python -m app.seed
"""
from datetime import date

from dotenv import load_dotenv

load_dotenv()

from app.db import Base, SessionLocal, engine
from app.models.models import (
    Meeting,
    MeetingStatus,
    Project,
    Stakeholder,
    Task,
    TaskStatus,
)

SAMPLE_STAKEHOLDERS = [
    ("Aisha Rahman", "aisha.rahman@example.com"),
    ("Daniel Tan", "daniel.tan@example.com"),
    ("Priya Nair", "priya.nair@example.com"),
    ("Marcus Wong", "marcus.wong@example.com"),
]

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


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        projects = {}
        for name, description in SAMPLE_PROJECTS:
            project = db.query(Project).filter_by(name=name).first()
            if project is None:
                project = Project(name=name, description=description)
                db.add(project)
                db.flush()
            projects[name] = project

        for name, email in SAMPLE_STAKEHOLDERS:
            if not db.query(Stakeholder).filter_by(name=name).first():
                db.add(Stakeholder(name=name, email=email))

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

        db.commit()
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
