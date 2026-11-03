"""Strict contracts for the review agent; model output never writes directly to the board."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, StrictInt, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReviewInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    meeting_date: date
    transcript: str = Field(min_length=20, max_length=60000)
    instructions: str = Field(default="", max_length=2000)
    check_duplicate: bool = True


class TaskFields(StrictModel):
    description: str = Field(min_length=1, max_length=4000)
    owner: Optional[str] = Field(max_length=200)
    deadline: Optional[date]
    status: Literal["todo", "in_progress", "done"]


    @field_validator("owner")
    @classmethod
    def empty_owner_is_unassigned(cls, value):
        return value or None


class Proposal(StrictModel):
    kind: Literal["update", "create"]
    task_id: Optional[int] = Field(gt=0)
    after: TaskFields
    evidence: str = Field(min_length=10, max_length=2000)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_target(self):
        if (self.kind == "update") != (self.task_id is not None):
            raise ValueError("Updates need an existing task_id; new tasks need null.")
        return self


class ReviewPlan(StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    proposals: list[Proposal] = Field(max_length=30)
    questions: list[str] = Field(max_length=15)


class ApplyInput(StrictModel):
    proposal_ids: list[StrictInt] = Field(max_length=30)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.proposal_ids)) != len(self.proposal_ids):
            raise ValueError("Each suggestion can be selected only once.")
        return self


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatInput(StrictModel):
    _used_evidence: list[str] = PrivateAttr(default_factory=list)
    message: str = Field(min_length=1, max_length=8000)
    current_date: date
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)


class ChatReference(StrictModel):
    kind: Literal["task", "meeting"]
    id: StrictInt
    quote: str = Field(min_length=1, max_length=2000)


class ChatAnswer(StrictModel):
    answer: str = Field(min_length=1, max_length=8000)
    references: list[ChatReference] = Field(max_length=30)
    proposals: list[Proposal] = Field(max_length=15)
    questions: list[str] = Field(max_length=10)
    next_action: Literal["none", "review_meeting"]
