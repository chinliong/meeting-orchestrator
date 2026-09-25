"""One-off migration: add meetings.summary to an existing database.

`create_all` on startup never alters existing tables, so a database that predates this column
(e.g. the Render/Neon Postgres one) needs it added by hand. Idempotent (`IF NOT EXISTS`) and
additive only - no data is touched or dropped, unlike `app/reset_db.py`.

Existing meetings keep a NULL summary until someone asks for one, and their tasks are unchanged.

Run from your own machine, pointed at the deployed database:

    DATABASE_URL="<your Neon connection string>" python -m app.migrate_add_meeting_summary
"""
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.db import engine

STATEMENTS = [
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS summary TEXT",
]


def migrate() -> None:
    print(f"Migrating {engine.url!r} — adding meetings.summary (existing data untouched)...")
    with engine.begin() as conn:
        for statement in STATEMENTS:
            print(f"  {statement}")
            conn.execute(text(statement))
    print("Done.")


if __name__ == "__main__":
    migrate()
