from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.llm.parser import TranscriptParser
from app.models.models import Meeting, MeetingStatus, Project, Task
from app.schemas.schemas import MeetingOut, TranscriptSubmit

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


@router.post("", response_model=MeetingOut, status_code=201)
def submit_transcript(payload: TranscriptSubmit, db: Session = Depends(get_db)):
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    meeting = Meeting(
        project_id=project.id,
        title=payload.title,
        transcript_text=payload.transcript_text,
        status=MeetingStatus.PROCESSING,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    try:
        extraction = TranscriptParser().parse(payload.transcript_text)
    except Exception as exc:  # LLM/API failure: record it on the meeting, don't crash the request
        meeting.status = MeetingStatus.FAILED
        meeting.error_message = str(exc)
        db.commit()
        db.refresh(meeting)
        return meeting

    for item in extraction.action_items:
        db.add(
            Task(
                project_id=project.id,
                meeting_id=meeting.id,
                description=item.description,
                owner=item.owner,
                deadline=item.deadline,
                confidence=item.confidence,
                source_decision=item.source_decision,
            )
        )

    meeting.status = MeetingStatus.COMPLETE
    db.commit()
    db.refresh(meeting)
    return meeting


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting
