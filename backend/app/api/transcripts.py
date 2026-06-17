from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.llm import transcription
from app.llm.parser import TranscriptParser
from app.models.models import Meeting, MeetingStatus, Project, Task
from app.schemas.schemas import MeetingOut, TranscriptSubmit

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


def _extract_and_store_tasks(meeting: Meeting, db: Session) -> None:
    """Run the LLM parser on the meeting's transcript and persist the extracted tasks.

    On LLM/API failure the meeting is marked FAILED with the error recorded rather than
    raising, so callers (sync request or background job) always leave a coherent meeting row.
    """
    try:
        extraction = TranscriptParser().parse(meeting.transcript_text)
    except Exception as exc:  # LLM/API failure: record it on the meeting, don't crash
        meeting.status = MeetingStatus.FAILED
        meeting.error_message = str(exc)
        db.commit()
        return

    for item in extraction.action_items:
        db.add(
            Task(
                project_id=meeting.project_id,
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


def _process_transcript(project: Project, title: str, transcript_text: str, db: Session) -> Meeting:
    """Persist a text meeting, run the parser synchronously, and return the result.

    Used by the text endpoint, where parsing is fast enough to do within the request.
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
    _extract_and_store_tasks(meeting, db)
    db.refresh(meeting)
    return meeting


def _transcribe_and_extract(meeting_id: int, data: bytes, suffix: str) -> None:
    """Background job: transcribe uploaded audio, then run the parser.

    Runs after the HTTP response is sent (in a worker thread), so it opens its own DB session —
    the request-scoped session is already closed. Doing transcription here, off the request,
    keeps the connection from being held open long enough for an upstream proxy to time it out
    (which the browser reported as an opaque "Failed to fetch").
    """
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:  # deleted before the job ran
            return
        try:
            meeting.transcript_text = transcription.transcribe_audio(data, suffix=suffix)
            db.commit()
        except (transcription.WhisperUnavailableError, transcription.TranscriptionError) as exc:
            meeting.status = MeetingStatus.FAILED
            meeting.error_message = str(exc)
            db.commit()
            return
        except Exception as exc:  # never leave the meeting stuck in PROCESSING
            meeting.status = MeetingStatus.FAILED
            meeting.error_message = f"Transcription failed: {exc}"
            db.commit()
            return
        _extract_and_store_tasks(meeting, db)
    finally:
        db.close()


@router.post("", response_model=MeetingOut, status_code=201)
def submit_transcript(payload: TranscriptSubmit, db: Session = Depends(get_db)):
    project = db.get(Project, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _process_transcript(project, payload.title, payload.transcript_text, db)


@router.post("/audio", response_model=MeetingOut, status_code=201)
async def submit_audio(
    background_tasks: BackgroundTasks,
    project_id: int = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Accept an audio/video upload and transcribe it in the background.

    Returns immediately with the meeting in PROCESSING status; the client polls
    GET /transcripts/{id} until it becomes COMPLETE or FAILED. Transcription runs off the
    request so a slow Whisper call can't time out the connection (which the browser reported
    as an opaque "Failed to fetch").
    """
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
    meeting = Meeting(
        project_id=project.id,
        title=title,
        transcript_text="",
        status=MeetingStatus.PROCESSING,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    background_tasks.add_task(_transcribe_and_extract, meeting.id, data, suffix)
    return meeting


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting
