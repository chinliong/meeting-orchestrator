"""One-off migration: add meetings.meeting_date to an existing database.

`create_all` on startup never alters existing tables, so a database that predates this column
(e.g. the Render/Neon Postgres one) needs it added by hand. Idempotent (`IF NOT EXISTS`) and
additive only - no data is touched or dropped, unlike `app/reset_db.py`.

Existing rows keep a NULL meeting_date and fall back to their created_at, which is the same
anchor they were parsed with, so nothing already on a board changes.

Run from your own machine, pointed at the deployed database:

    DATABASE_URL="<your Neon connection string>" python -m app.migrate_add_meeting_date
"""
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.db import engine

STATEMENTS = [
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS meeting_date DATE",
]


def migrate() -> None:
    print(f"Migrating {engine.url!r} — adding meetings.meeting_date (existing data untouched)...")
    with engine.begin() as conn:
        for statement in STATEMENTS:
            print(f"  {statement}")
            conn.execute(text(statement))
    print("Done.")


if __name__ == "__main__":
    migrate()
