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


class ProjectOut(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class StakeholderCreate(BaseModel):
    name: str
    email: Optional[str] = None


class StakeholderOut(StakeholderCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class TranscriptSubmit(BaseModel):
    project_id: int
    title: str
    transcript_text: str


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    meeting_id: Optional[int]
    description: str
    owner: Optional[str]
    deadline: Optional[date]
    status: TaskStatus
    confidence: float
    source_decision: Optional[str]
    created_at: datetime


class TaskUpdate(BaseModel):
    description: Optional[str] = None
    owner: Optional[str] = None
    deadline: Optional[date] = None
    status: Optional[TaskStatus] = None


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
    confidence: float = 1.0
    source_decision: Optional[str] = None


class ExtractionResult(BaseModel):
    decisions: list[str] = []
    action_items: list[ExtractedActionItem] = []
