"""Send due-date / overdue email reminders to opted-in account holders.

Run once a day, e.g. as a Render Cron Job (separate from the always-on web service) or a
local cron entry:

    python -m app.notify_due_tasks
"""
from dotenv import load_dotenv

load_dotenv()

from app.db import SessionLocal
from app.notifications import send_due_date_notifications


def main() -> None:
    db = SessionLocal()
    try:
        sent = send_due_date_notifications(db)
        print(f"Sent {sent} notification email(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
