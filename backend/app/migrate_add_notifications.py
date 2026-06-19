"""One-off migration: add the deadline-reminder columns to an existing database.

`create_all` on startup never alters existing tables, so a DB that predates the notification
feature (e.g. the Render/Neon Postgres database) needs these columns added by hand. This is
idempotent (`IF NOT EXISTS`) and additive only — no data is touched or dropped, unlike
`app/reset_db.py`.

Run from your own machine, pointed at the deployed database:

    DATABASE_URL="<your Neon connection string>" python -m app.migrate_add_notifications
"""
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from app.db import engine

STATEMENTS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_email BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_days_before INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS notify_muted BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS last_notified_for DATE",
]


def migrate() -> None:
    print(f"Migrating {engine.url!r} — adding notification columns (existing data is untouched)...")
    with engine.begin() as conn:
        for statement in STATEMENTS:
            print(f"  {statement}")
            conn.execute(text(statement))
    print("Done.")


if __name__ == "__main__":
    migrate()
