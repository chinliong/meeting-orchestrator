"""Unit tests for the deadline-reminder window/idempotency logic in app.notifications.

Exercises send_due_date_notifications() directly against the DB (rather than through the
HTTP API) so each test can pin an exact `today` and inspect exactly what would be emailed.
"""
from datetime import date, timedelta

import pytest

from app.auth import hash_password
from app.models.models import Project, Task, TaskStatus, User
from app.notifications import send_due_date_notifications

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


def _make_project(db, user, muted=False):
    project = Project(name="P", owner_user_id=user.id, notify_muted=muted)
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


def test_respects_project_mute(db_session, sent_emails):
    user = _make_user(db_session)
    project = _make_project(db_session, user, muted=True)
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


def test_digests_multiple_tasks_into_one_email(db_session, sent_emails):
    user = _make_user(db_session)
    project = _make_project(db_session, user)
    _make_task(db_session, project, deadline=TODAY)
    _make_task(db_session, project, deadline=TODAY + timedelta(days=1))
    db_session.commit()

    assert send_due_date_notifications(db_session, today=TODAY) == 1  # one email...
    assert len(sent_emails) == 1
    assert "2 tasks" in sent_emails[0]["subject"]  # ...covering both tasks


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
