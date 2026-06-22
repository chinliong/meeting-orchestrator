"""Deadline email reminders.

A single daily pass (`send_due_date_notifications`) finds every task that has just entered
its reminder window — from `notify_days_before` days out through one day after the
deadline (a one-time overdue nudge, not a repeating one) — and emails each affected account
holder a single digest covering all of their newly-due tasks across every reminder-enabled project.

Idempotency is tracked per task via `Task.last_notified_for`: once a task has been notified
for a given deadline, re-running the same day (or after the deadline) never re-sends. Changing
a task's deadline clears that match, so a rescheduled task gets a fresh reminder.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, selectinload

from app.email import send_email
from app.models.models import Project, Task, TaskStatus, User

# uvicorn configures this logger at INFO, so failures show up in the Render logs.
log = logging.getLogger("uvicorn.error")


class NotificationSendError(RuntimeError):
    """Raised when the email provider itself fails (e.g. Brevo rejects or times out)."""


def _reminder_today() -> date:
    """Today's date for the reminder window, in REMINDER_TIMEZONE if set.

    The window is date-based, so which calendar day "now" falls on decides whether a task is
    in range. The server clock is UTC, which can be a day off for users elsewhere (a task due
    "Jun 24" enters its window at 08:00 SGT on Jun 23), so the timezone is configurable, e.g.
    REMINDER_TIMEZONE=Asia/Singapore. Unset keeps the old behaviour (server/UTC date); an
    invalid value falls back to it with a warning rather than crashing the daily run.
    """
    tz_name = os.getenv("REMINDER_TIMEZONE")
    if not tz_name:
        return date.today()
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        log.warning("notifications: invalid REMINDER_TIMEZONE %r; using server date", tz_name)
        return date.today()


def _in_notify_window(today: date, deadline: date, days_before: int) -> bool:
    window_start = deadline - timedelta(days=days_before)
    window_end = deadline + timedelta(days=1)  # one day of grace for an overdue nudge
    return window_start <= today <= window_end


def _candidate_tasks(db: Session, user_id: int | None = None) -> list[Task]:
    """Open tasks with a deadline, belonging to an account holder who has opted in
    account-wide and has enabled reminders for that particular project."""
    query = (
        db.query(Task)
        .options(selectinload(Task.subtasks))  # for the digest's subtask progress/open items
        .join(Project, Task.project_id == Project.id)
        .join(User, Project.owner_user_id == User.id)
        .filter(
            Task.status != TaskStatus.DONE,
            Task.deadline.isnot(None),
            Project.notify_enabled.is_(True),
            User.notify_email.is_(True),
        )
    )
    if user_id is not None:
        query = query.filter(User.id == user_id)
    return query.all()


def _format_digest(tasks: list[Task], today: date) -> tuple[str, str]:
    lines = []
    for task in sorted(tasks, key=lambda t: t.deadline):
        if task.deadline < today:
            tag = "OVERDUE"
        elif task.deadline == today:
            tag = "DUE TODAY"
        else:
            tag = f"due {task.deadline:%b %d}"
        owner = f" — {task.owner}" if task.owner else ""

        # Surface subtask progress on the task line, then list the still-open subtasks beneath
        # so the reminder is actionable rather than just a heads-up.
        subtasks = task.subtasks
        progress = ""
        if subtasks:
            done = sum(1 for s in subtasks if s.done)
            progress = f" · {done}/{len(subtasks)} subtasks done"
        lines.append(f"- [{tag}] {task.description}{owner} ({task.project.name}){progress}")
        for sub in subtasks:
            if not sub.done:
                lines.append(f"    ◦ {sub.title}")

    subject = f"{len(tasks)} task{'s' if len(tasks) != 1 else ''} need attention"
    body = "Reminder from Meeting Orchestrator:\n\n" + "\n".join(lines)
    return subject, body


def send_due_date_notifications(db: Session, today: date | None = None) -> int:
    """Send one digest email per account holder who has newly-due or newly-overdue tasks.

    Returns the number of emails actually sent. Runs once a day via an external trigger (see
    `app/notify_due_tasks.py` and `GET /internal/notify-due-tasks`) with nobody watching, so a
    transient failure sending to one user (e.g. the email provider hiccups) is caught and
    logged rather than raised — it must not block every other user's reminder, or look like the
    whole job failed. That user's tasks are simply left unmarked and picked up on the next run.
    """
    today = today or _reminder_today()

    by_user: dict[int, list[Task]] = {}
    for task in _candidate_tasks(db):
        if task.last_notified_for == task.deadline:
            continue
        user = task.project.owner
        if not _in_notify_window(today, task.deadline, user.notify_days_before):
            continue
        by_user.setdefault(user.id, []).append(task)

    sent = 0
    for tasks in by_user.values():
        user = tasks[0].project.owner
        subject, body = _format_digest(tasks, today)
        try:
            send_email(to=user.email, subject=subject, body=body)
        except Exception:
            log.exception("notifications: failed to send digest to %s", user.email)
            continue
        for task in tasks:
            task.last_notified_for = task.deadline
        db.commit()  # commit per user, so one later failure can't lose an earlier success
        sent += 1
    return sent


def send_test_notification(db: Session, user: User) -> int:
    """Manually trigger a preview digest for one user (the Account settings "send test
    email" button). Ignores `last_notified_for` so it can be re-clicked, and sends even
    when there's nothing currently due — confirming the email channel itself works.
    """
    today = _reminder_today()
    tasks = [
        task
        for task in _candidate_tasks(db, user_id=user.id)
        if _in_notify_window(today, task.deadline, user.notify_days_before)
    ]
    if tasks:
        subject, body = _format_digest(tasks, today)
    else:
        subject = "Test reminder — no tasks due right now"
        body = (
            "This is a test of your Meeting Orchestrator deadline reminders.\n\n"
            "You don't have any tasks currently due or overdue, but notifications are "
            "working."
        )
    try:
        send_email(to=user.email, subject=subject, body=body)
    except Exception as exc:
        # A button click has someone actually watching, so surface this as a clean error
        # instead of letting the email provider's raw exception become an opaque 500.
        raise NotificationSendError(str(exc)) from exc
    return len(tasks)
