from __future__ import annotations

import enum
import secrets
from datetime import date

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import column_property, relationship
from sqlalchemy.sql import func

from app.db import Base


def _new_token() -> str:
    """An unguessable, permanent capability token for a share link."""
    return secrets.token_urlsafe(32)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    # Deadline email reminders are opt-in (default off) — see app/notifications.py.
    notify_email = Column(Boolean, nullable=False, default=False)
    notify_days_before = Column(Integer, nullable=False, default=1)

    projects = relationship("Project", back_populates="owner")
    # Boards shared with this user whose reminders they asked for; see ReminderSubscription.
    reminder_subscriptions = relationship(
        "ReminderSubscription", back_populates="user", cascade="all, delete-orphan"
    )


class PasswordReset(Base):
    """A short-lived 6-digit code emailed to a user to reset their password.

    Only the bcrypt hash of the code is stored. A code is single-use (`used`) and
    expires; `attempts` caps brute-force guesses.
    """

    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now())


class TaskStatus(str, enum.Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class MeetingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())

    # Null owner = a guest-created board, reachable only via its share links.
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # Permanent capability tokens: holding the link is the credential.
    view_token = Column(String, nullable=False, unique=True, index=True, default=_new_token)
    edit_token = Column(String, nullable=False, unique=True, index=True, default=_new_token)
    # Per-project opt-in: deadline reminders are sent for this board only if this is on AND the
    # owner has reminders enabled account-wide. Off by default — the owner picks which boards
    # should remind them.
    notify_enabled = Column(Boolean, nullable=False, default=False)

    owner = relationship("User", back_populates="projects")
    meetings = relationship("Meeting", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    reminder_subscriptions = relationship(
        "ReminderSubscription", back_populates="project", cascade="all, delete-orphan"
    )


class Stakeholder(Base):
    __tablename__ = "stakeholders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=True)


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    title = Column(String, nullable=False)
    transcript_text = Column(Text, nullable=False)
    # The date the meeting took place. Relative deadline cues ("by Friday") resolve against it,
    # so a transcript of a past meeting does not anchor to whenever it was uploaded. Nullable
    # for rows created before this column existed; those fall back to created_at.
    meeting_date = Column(Date, nullable=True)
    status = Column(Enum(MeetingStatus), default=MeetingStatus.PENDING, nullable=False)
    error_message = Column(Text, nullable=True)
    # An AI summary of the meeting (overview, decisions, open items) as JSON, written by a
    # separate request after extraction (app/llm/summary.py). NULL until one has been made.
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    project = relationship("Project", back_populates="meetings")
    tasks = relationship("Task", back_populates="meeting", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=True)
    description = Column(Text, nullable=False)
    owner = Column(String, nullable=True)
    deadline = Column(Date, nullable=True)
    status = Column(Enum(TaskStatus), default=TaskStatus.TODO, nullable=False)
    confidence = Column(Float, default=1.0)
    source_decision = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    # The deadline (if any) this task last sent an email reminder for — keeps the daily
    # notification job from re-sending for a deadline it already warned about.
    last_notified_for = Column(Date, nullable=True)

    project = relationship("Project", back_populates="tasks")
    meeting = relationship("Meeting", back_populates="tasks")
    # A task can be broken down into a checklist of subtasks (often AI-generated) and can carry
    # file attachments. Both are removed with the task.
    subtasks = relationship(
        "Subtask",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="Subtask.position, Subtask.id",
    )
    attachments = relationship(
        "Attachment",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="Attachment.created_at",
    )
    subscriber_reminders = relationship(
        "SubscriberReminder", back_populates="task", cascade="all, delete-orphan"
    )

    @property
    def meeting_title(self) -> str | None:
        """Title of the source meeting, or None for manually-added tasks."""
        return self.meeting.title if self.meeting else None

    @property
    def meeting_date(self) -> date | None:
        """Date of the source meeting, or None for manually-added tasks.

        Shown beside the title so meetings that share a title stay distinguishable. Meetings
        created before `meeting_date` existed fall back to their upload date.
        """
        if self.meeting is None:
            return None
        if self.meeting.meeting_date:
            return self.meeting.meeting_date
        return self.meeting.created_at.date() if self.meeting.created_at else None


class Subtask(Base):
    """A single checklist item under a Task. Used for the AI task-breakdown feature."""

    __tablename__ = "subtasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    # Manual ordering within a task; AI-generated items keep the order the model returned.
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())

    task = relationship("Task", back_populates="subtasks")


class Attachment(Base):
    """A file attached to a Task.

    The bytes are stored in the database (BYTEA/BLOB) rather than on disk: the deployment
    target (Render free tier) has an ephemeral filesystem and no object storage, so a row in
    the DB is the only thing that survives a restart. Uploads are size-capped in the API.
    """

    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False, default="application/octet-stream")
    size = Column(Integer, nullable=False)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    task = relationship("Task", back_populates="attachments")


class ReminderSubscription(Base):
    """A signed-in collaborator who asked for a shared board's deadline reminders.

    The board's owner is reminded through their own settings; this lets someone the board was
    shared with receive the same digest for it. It records which share link (`via`: "view" or
    "edit") gave them access, so regenerating that link, which revokes their access, also ends
    their reminders. Only boards with an owner can be subscribed to, since a guest board has
    nobody who could revoke access.
    """

    __tablename__ = "reminder_subscriptions"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    via = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    project = relationship("Project", back_populates="reminder_subscriptions")
    user = relationship("User", back_populates="reminder_subscriptions")
    sent = relationship("SubscriberReminder", back_populates="subscription", cascade="all, delete-orphan")


class SubscriberReminder(Base):
    """The deadline a subscriber was last reminded about for one task.

    The owner's reminders are tracked on the task itself (`Task.last_notified_for`); each
    subscriber needs their own record, or one person's email would mark the task as reminded
    for everyone.
    """

    __tablename__ = "subscriber_reminders"
    __table_args__ = (UniqueConstraint("subscription_id", "task_id"),)

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey("reminder_subscriptions.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    notified_for = Column(Date, nullable=False)

    subscription = relationship("ReminderSubscription", back_populates="sent")
    task = relationship("Task", back_populates="subscriber_reminders")


# Lightweight rollup counts exposed on every Task without loading the child rows (in particular
# without pulling attachment blobs). Added as correlated scalar subqueries so they ride along in
# the same SELECT that loads the task — no extra round trip and no N+1.
Task.subtask_total = column_property(
    select(func.count(Subtask.id)).where(Subtask.task_id == Task.id).scalar_subquery(),
    deferred=False,
)
Task.subtask_done = column_property(
    select(func.count(Subtask.id))
    .where(Subtask.task_id == Task.id, Subtask.done == True)  # noqa: E712
    .scalar_subquery(),
    deferred=False,
)
Task.attachment_count = column_property(
    select(func.count(Attachment.id)).where(Attachment.task_id == Task.id).scalar_subquery(),
    deferred=False,
)
