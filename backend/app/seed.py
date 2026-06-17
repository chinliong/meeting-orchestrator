"""Seed the database with a sample project and stakeholders.

Run with: python -m app.seed
"""
from dotenv import load_dotenv

load_dotenv()

from app.db import Base, SessionLocal, engine
from app.models.models import Project, Stakeholder

SAMPLE_STAKEHOLDERS = [
    ("Aisha Rahman", "aisha.rahman@example.com"),
    ("Daniel Tan", "daniel.tan@example.com"),
    ("Priya Nair", "priya.nair@example.com"),
    ("Marcus Wong", "marcus.wong@example.com"),
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if not db.query(Project).filter_by(name="SAP S/4HANA Go-Live Programme").first():
            project = Project(
                name="SAP S/4HANA Go-Live Programme",
                description="Cross-functional workshops tracking action items ahead of go-live.",
            )
            db.add(project)

        for name, email in SAMPLE_STAKEHOLDERS:
            if not db.query(Stakeholder).filter_by(name=name).first():
                db.add(Stakeholder(name=name, email=email))

        db.commit()
        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
