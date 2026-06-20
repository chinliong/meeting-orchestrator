"""One-off migration: switch per-project reminders from opt-out to opt-in.

The reminder model changed from `projects.notify_muted` (reminders on unless muted) to
`projects.notify_enabled` (reminders off unless explicitly enabled). `create_all` never alters
existing tables, so this adds the new column to a database that predates the change.

It is additive and idempotent: it adds `notify_enabled` only if missing, and seeds it from the
old flag (`notify_enabled = NOT notify_muted`) so boards that were being reminded keep being
reminded. The old `notify_muted` column is left in place (harmless) rather than dropped, since
dropping columns on SQLite is awkward and the app no longer reads it.

Run from your machine, pointed at the database you want to migrate:

    DATABASE_URL="<connection string>" python -m app.migrate_reminder_optin
"""
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import inspect, text

from app.db import engine


def migrate() -> None:
    print(f"Migrating {engine.url!r} — adding projects.notify_enabled (opt-in reminders)...")
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("projects")}

    if "notify_enabled" in columns:
        print("  notify_enabled already present — nothing to do.")
        return

    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE projects ADD COLUMN notify_enabled BOOLEAN NOT NULL DEFAULT FALSE")
        )
        print("  added column notify_enabled (default FALSE)")
        if "notify_muted" in columns:
            # Preserve current behaviour: an un-muted board was being reminded → enable it.
            conn.execute(text("UPDATE projects SET notify_enabled = (NOT notify_muted)"))
            print("  seeded notify_enabled = NOT notify_muted for existing boards")
    print("Done.")


if __name__ == "__main__":
    migrate()
