from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.llm import transcription
from app.llm.parser import TranscriptParser
from app.models.models import Meeting, MeetingStatus, Project, Task
from app.schemas.schemas import MeetingOut, TranscriptSubmit

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def _process_transcript(project: Project, title: str, transcript_text: str, db: Session) -> Meeting:
    """Persist a meeting, run the LLM parser, and store the extracted tasks.

    Shared by the text and audio submission endpoints. LLM/API failures are recorded on
    the meeting (status FAILED) rather than raised, so the client always gets a meeting back.
    """
    meeting = Meeting(
        project_id=project.id,
        title=title,
        transcript_text=transcript_text,
        status=MeetingStatus.PROCESSING,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    try:
        extraction = TranscriptParser().parse(transcript_text)
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
                status=item.status,
                confidence=item.confidence,
                source_decision=item.source_decision,
            )
        )

    meeting.status = MeetingStatus.COMPLETE
    db.commit()
    db.refresh(meeting)
    return meeting


@router.post("", response_model=MeetingOut, status_code=201)
def submit_transcript(payload: TranscriptSubmit, db: Session = Depends(get_db)):
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _process_transcript(project, payload.title, payload.transcript_text, db)


@router.post("/audio", response_model=MeetingOut, status_code=201)
async def submit_audio(
    project_id: int = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Transcribe an uploaded audio/video file with Whisper, then run the same pipeline."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not transcription.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Audio transcription is not configured. Set TRANSCRIPTION_API_KEY to use a "
                "hosted Whisper API, or install local Whisper with "
                "`pip install -r requirements-audio.txt`."
            ),
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    suffix = "." + file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else ".wav"
    try:
        transcript_text = transcription.transcribe_audio(data, suffix=suffix)
    except transcription.WhisperUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return _process_transcript(project, title, transcript_text, db)


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting
