"""Unit tests for the deadline-reminder window/idempotency logic in app.notifications.

Exercises send_due_date_notifications() directly against the DB (rather than through the
HTTP API) so each test can pin an exact `today` and inspect exactly what would be emailed.
"""
from datetime import date, timedelta

import pytest

from app.auth import hash_password
from app.models.models import Project, Subtask, Task, TaskStatus, User
from app.notifications import NotificationSendError, send_due_date_notifications, send_test_notification

TODAY = date(2026, 6, 20)


def _make_user(db, email="owner@example.com", notify=True, days_before=1):
    user = User(
        email=email,
        password_hash=hash_password("pw"),
        notify_email=notify,
        notify_days_before=days_before,
    )
    db.add(user)
    db.flush()
    return user


def _make_project(db, user, enabled=True):
    # Reminders are opt-in per project; most tests want a reminder to fire, so default it on.
    project = Project(name="P", owner_user_id=user.id, notify_enabled=enabled)
    db.add(project)
    db.flush()
    return project


def _make_task(db, project, deadline, status=TaskStatus.TODO, last_notified_for=None):
    task = Task(
        project_id=project.id,
        description="t",
        deadline=deadline,
        status=status,
        last_notified_for=last_notified_for,
    )
    db.add(task)
    db.flush()
    return task


@pytest.fixture()
def sent_emails(monkeypatch):
    calls = []
    monkeypatch.setattr("app.notifications.send_email", lambda **kwargs: calls.append(kwargs))
    return calls


def test_sends_for_task_due_tomorrow_with_one_day_threshold(db_session, sent_emails):
    user = _make_user(db_session, days_before=1)
    project = _make_project(db_session, user)
    _make_task(db_session, project, deadline=TODAY + timedelta(days=1))
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 1
    assert sent_emails[0]["to"] == user.email


def test_does_not_send_before_window_opens(db_session, sent_emails):
    user = _make_user(db_session, days_before=1)
    project = _make_project(db_session, user)
    _make_task(db_session, project, deadline=TODAY + timedelta(days=3))
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 0
    assert sent_emails == []


def test_sends_once_for_overdue_then_stops(db_session, sent_emails):
    user = _make_user(db_session, days_before=1)
    project = _make_project(db_session, user)
    _make_task(db_session, project, deadline=TODAY - timedelta(days=1))
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 1
    # Re-running the same day must not double-send.
    assert send_due_date_notifications(db_session, today=TODAY) == 0
    assert len(sent_emails) == 1


def test_silent_once_grace_period_has_passed(db_session, sent_emails):
    user = _make_user(db_session, days_before=1)
    project = _make_project(db_session, user)
    _make_task(db_session, project, deadline=TODAY - timedelta(days=5))
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 0
    assert sent_emails == []


def test_respects_opt_out(db_session, sent_emails):
    user = _make_user(db_session, notify=False)
    project = _make_project(db_session, user)
    _make_task(db_session, project, deadline=TODAY)
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 0
    assert sent_emails == []


def test_respects_project_not_enabled(db_session, sent_emails):
    # A board with reminders left off (the default) sends nothing, even for a due task.
    user = _make_user(db_session)
    project = _make_project(db_session, user, enabled=False)
    _make_task(db_session, project, deadline=TODAY)
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 0
    assert sent_emails == []


def test_ignores_done_tasks(db_session, sent_emails):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    _make_task(db_session, project, deadline=TODAY, status=TaskStatus.DONE)
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 0
    assert sent_emails == []


def test_digest_includes_subtask_progress_and_open_items(db_session, sent_emails):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    task = _make_task(db_session, project, deadline=TODAY)
    db_session.add_all(
        [
            Subtask(task_id=task.id, title="Export records", done=True, position=0),
            Subtask(task_id=task.id, title="Validate mapping", done=False, position=1),
            Subtask(task_id=task.id, title="Get sign-off", done=False, position=2),
        ]
    )
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 1
    body = sent_emails[0]["body"]
    assert "1/3 subtasks done" in body
    # Open subtasks are listed; the completed one is not.
    assert "Validate mapping" in body
    assert "Get sign-off" in body
    assert "Export records" not in body


def test_digests_multiple_tasks_into_one_email(db_session, sent_emails):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    _make_task(db_session, project, deadline=TODAY)
    _make_task(db_session, project, deadline=TODAY + timedelta(days=1))
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 1  # one email...
    assert len(sent_emails) == 1
    assert "2 tasks" in sent_emails[0]["subject"]  # ...covering both tasks


def test_one_users_send_failure_does_not_block_others(db_session, monkeypatch):
    """A transient email-provider failure for one user must not crash the whole batch or
    swallow other users' reminders — see the cron-job.org 500-then-200 retry incident."""
    failing_user = _make_user(db_session, email="fails@example.com")
    failing_project = _make_project(db_session, failing_user)
    _make_task(db_session, failing_project, deadline=TODAY)

    ok_user = _make_user(db_session, email="ok@example.com")
    ok_project = _make_project(db_session, ok_user)
    ok_task = _make_task(db_session, ok_project, deadline=TODAY)
    db_session.commit()

    sent_to = []

    def flaky_send(to, **kwargs):
        if to == "fails@example.com":
            raise RuntimeError("simulated transient provider failure")
        sent_to.append(to)

    monkeypatch.setattr("app.notifications.send_email", flaky_send)

    sent = send_due_date_notifications(db_session, today=TODAY)
    assert sent == 1
    assert sent_to == ["ok@example.com"]
    # The failed user's task is left unmarked so the next run retries it.
    assert ok_task.last_notified_for == TODAY


def test_send_due_date_notifications_never_raises_on_provider_failure(db_session, monkeypatch):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    _make_task(db_session, project, deadline=TODAY)
    db_session.commit()

    monkeypatch.setattr(
        "app.notifications.send_email",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    # Must not raise — a daily unattended job can't crash on a provider hiccup.
    assert send_due_date_notifications(db_session, today=TODAY) == 0


def test_rescheduled_task_reopens_window(db_session, sent_emails):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    task = _make_task(db_session, project, deadline=TODAY, last_notified_for=TODAY)
    db_session.commit()

    # Already notified for this exact deadline.
    assert send_due_date_notifications(db_session, today=TODAY) == 0

    # Deadline moves -> last_notified_for no longer matches -> fresh reminder.
    task.deadline = TODAY + timedelta(days=1)
    db_session.commit()
    assert send_due_date_notifications(db_session, today=TODAY) == 1


def test_test_notification_surfaces_provider_failure_as_clean_error(db_session, monkeypatch):
    """A manual 'send test email' click has someone watching, so unlike the daily batch job,
    a provider failure here should raise a clear error instead of being swallowed."""
    user = _make_user(db_session)
    db_session.commit()

    monkeypatch.setattr(
        "app.notifications.send_email",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(NotificationSendError):
        send_test_notification(db_session, user)
