from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.models import MeetingStatus, TaskStatus


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime
    owner_user_id: Optional[int] = None
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


class AuthResponse(BaseModel):
    token: str
    user: UserOut


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
