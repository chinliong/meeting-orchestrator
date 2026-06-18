"""Drop every table and recreate it from the current models, then seed.

Use this to reset a database after a schema change (e.g. adding accounts and share
tokens), since `create_all` on startup never alters existing tables. Runs against
whatever DATABASE_URL points at — locally that's SQLite, on Render it's Postgres.

DESTRUCTIVE: this deletes all existing data. Run with:

    python -m app.reset_db
"""
from dotenv import load_dotenv

load_dotenv()

from app.db import Base, engine
from app.models import models  # noqa: F401  (registers all tables on the metadata)
from app.seed import seed


def reset() -> None:
    print(f"Resetting database at {engine.url!r} — dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("Schema rebuilt. Seeding demo data...")
    seed()


if __name__ == "__main__":
    reset()
