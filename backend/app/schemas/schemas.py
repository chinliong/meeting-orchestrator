from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.models import MeetingStatus, TaskStatus


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    notify_enabled: Optional[bool] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    owner_user_id: Optional[int] = None
    notify_enabled: bool
    # The caller's access to this board, and the tokens they're allowed to see.
    access_level: str  # "edit" | "view"
    view_token: str
    edit_token: Optional[str] = None  # omitted for view-only callers


class SignupRequest(BaseModel):
    email: str
    password: str
    # Edit tokens of guest boards to adopt into the new account (carry-over on signup).
    claim_tokens: list[str] = []


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime
    notify_email: bool
    notify_days_before: int


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class NotificationSettingsUpdate(BaseModel):
    notify_email: bool
    notify_days_before: int = Field(default=1, ge=0, le=14)


class StakeholderCreate(BaseModel):
    name: str
    email: Optional[str] = None


class StakeholderOut(StakeholderCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class TranscriptSubmit(BaseModel):
    project_id: int
    title: str = ""
    transcript_text: str


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    meeting_id: Optional[int]
    meeting_title: Optional[str] = None
    description: str
    owner: Optional[str]
    deadline: Optional[date]
    status: TaskStatus
    confidence: float
    source_decision: Optional[str]
    created_at: datetime
    # Rollup counts (computed on the model) so cards can show progress without fetching children.
    subtask_total: int = 0
    subtask_done: int = 0
    attachment_count: int = 0


class TaskCreate(BaseModel):
    project_id: int
    description: str
    owner: Optional[str] = None
    deadline: Optional[date] = None
    status: TaskStatus = TaskStatus.TODO


class TaskUpdate(BaseModel):
    description: Optional[str] = None
    owner: Optional[str] = None
    deadline: Optional[date] = None
    status: Optional[TaskStatus] = None


class DeletedTask(BaseModel):
    """Snapshot returned by DELETE /tasks/{id} so the client can offer an undo."""

    task: TaskOut


class TaskRestoreData(BaseModel):
    # Extra fields from a TaskOut snapshot (meeting_title, created_at) are ignored.
    id: int
    project_id: int
    meeting_id: Optional[int] = None
    description: str
    owner: Optional[str] = None
    deadline: Optional[date] = None
    status: TaskStatus = TaskStatus.TODO
    confidence: float = 1.0
    source_decision: Optional[str] = None


class TaskRestore(BaseModel):
    task: TaskRestoreData


class MeetingUpdate(BaseModel):
    title: str


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    status: MeetingStatus
    error_message: Optional[str]
    created_at: datetime
    tasks: list[TaskOut] = []


class SubtaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    title: str
    done: bool
    position: int


class SubtaskCreate(BaseModel):
    title: str


class SubtaskUpdate(BaseModel):
    title: Optional[str] = None
    done: Optional[bool] = None


class SubtaskGenerate(BaseModel):
    """Request body for AI subtask generation.

    When `instructions` is non-empty the model is steered by the user's wording ("from your
    instructions"); otherwise it breaks the task down from its own details ("from task details").
    """

    instructions: Optional[str] = None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    filename: str
    content_type: str
    size: int
    created_at: datetime


class ExtractedActionItem(BaseModel):
    description: str
    owner: Optional[str] = None
    deadline: Optional[date] = None
    status: TaskStatus = TaskStatus.TODO
    confidence: float = 1.0
    source_decision: Optional[str] = None


class ExtractionResult(BaseModel):
    decisions: list[str] = []
    action_items: list[ExtractedActionItem] = []
