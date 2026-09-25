import logging
import os
import tempfile
from datetime import date
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_optional_user, require_project_edit, require_project_view
from app.db import SessionLocal, get_db
from app.llm import transcription
from app.llm.parser import TranscriptParser
from app.models.models import Meeting, MeetingStatus, Project, Task, User
from app.schemas.schemas import MeetingListItem, MeetingOut, MeetingUpdate, TranscriptSubmit

router = APIRouter(prefix="/transcripts", tags=["transcripts"])

log = logging.getLogger("uvicorn.error")

# Largest audio/video upload accepted. Uploads are streamed to disk rather than held in memory,
# so this bounds disk use and transcription time rather than RAM. Keep it in step with the
# frontend check in TranscriptUpload.tsx.
MAX_AUDIO_BYTES = 500 * 1024 * 1024  # 500 MB
_UPLOAD_CHUNK = 1024 * 1024


def _meeting_title(title: str, on: date) -> str:
    """Fall back to a dated label when the user leaves the title blank."""
    return title.strip() or f"Meeting · {on:%b %d, %Y}"


def _parse_form_date(value: str) -> Optional[date]:
    """Read the multipart date field. Blank or malformed means 'not supplied'."""
    try:
        return date.fromisoformat(value.strip()) if value.strip() else None
    except ValueError:
        return None


def _anchor(meeting: Meeting) -> date:
    """The date relative deadline cues resolve against.

    The supplied meeting date wins; otherwise the upload date, which is the best available
    proxy. Deliberately never inferred from the transcript text - a date mentioned in passing
    (a freeze date, a go-live) would anchor every deadline to the wrong day, silently.
    """
    if meeting.meeting_date:
        return meeting.meeting_date
    return meeting.created_at.date() if meeting.created_at else date.today()


def _extract_and_store_tasks(meeting: Meeting, db: Session) -> None:
    """Run the LLM parser on the meeting's transcript and persist the extracted tasks.

    On LLM/API failure the meeting is marked FAILED with the error recorded rather than
    raising, so callers (sync request or background job) always leave a coherent meeting row.
    """
    try:
        # TranscriptParser.parse logs the provider, model and elapsed time itself.
        extraction = TranscriptParser().parse(meeting.transcript_text,
                                              meeting_date=_anchor(meeting))
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


def _process_transcript(project: Project, title: str, transcript_text: str, db: Session,
                        meeting_date: Optional[date] = None) -> Meeting:
    """Persist a text meeting, run the parser synchronously, and return the result.

    Used by the text endpoint, where parsing is fast enough to do within the request.
    """
    meeting = Meeting(
        project_id=project.id,
        title=title,
        transcript_text=transcript_text,
        meeting_date=meeting_date,
        status=MeetingStatus.PROCESSING,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    _extract_and_store_tasks(meeting, db)
    db.refresh(meeting)
    return meeting


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=413,
        detail=f"File is too large. The limit is {MAX_AUDIO_BYTES // (1024 * 1024)} MB.",
    )


async def _save_upload(file: UploadFile, suffix: str) -> str:
    """Stream an upload to a temporary file and return its path.

    The recording is copied in chunks and never held in memory whole: a long meeting video can
    be hundreds of megabytes, more than the free-tier instance's RAM. Raises 413 over the size
    limit and 400 for an empty file, removing the partial file in both cases.
    """
    if file.size is not None and file.size > MAX_AUDIO_BYTES:
        raise _too_large()
    fd, path = tempfile.mkstemp(suffix=suffix)
    written = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_AUDIO_BYTES:
                    raise _too_large()
                out.write(chunk)
        if written == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
    except BaseException:
        os.unlink(path)
        raise
    return path


def _transcribe_and_extract(meeting_id: int, path: str) -> None:
    """Background job: transcribe the uploaded recording at `path`, then run the parser.

    Runs after the HTTP response is sent (in a worker thread), so it opens its own DB session —
    the request-scoped session is already closed. Doing transcription here, off the request,
    keeps the connection from being held open long enough for an upstream proxy to time it out
    (which the browser reported as an opaque "Failed to fetch"). The job owns the temporary
    file and removes it whatever the outcome.
    """
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:  # deleted before the job ran
            return
        try:
            meeting.transcript_text = transcription.transcribe_file(path)
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
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


@router.post("", response_model=MeetingOut, status_code=201)
def submit_transcript(
    payload: TranscriptSubmit,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    project = require_project_edit(db, payload.project_id, user, x_workspace_token)
    if payload.check_duplicate:
        # An accidental second paste of the same transcript would duplicate every task.
        existing = (
            db.query(Meeting)
            .filter(Meeting.project_id == project.id, Meeting.transcript_text == payload.transcript_text)
            .order_by(Meeting.created_at.desc(), Meeting.id.desc())
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "duplicate_transcript",
                    "message": "This transcript has already been added to this board.",
                    "meeting": {
                        "id": existing.id,
                        "title": existing.title,
                        "created_at": existing.created_at.isoformat() if existing.created_at else None,
                    },
                },
            )
    on = payload.meeting_date or date.today()
    return _process_transcript(project, _meeting_title(payload.title, on),
                               payload.transcript_text, db, meeting_date=on)


@router.post("/audio", response_model=MeetingOut, status_code=201)
async def submit_audio(
    background_tasks: BackgroundTasks,
    project_id: int = Form(...),
    title: str = Form(""),
    meeting_date: str = Form(""),
    file: UploadFile = File(...),
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Accept an audio/video upload and transcribe it in the background.

    Returns immediately with the meeting in PROCESSING status; the client polls
    GET /transcripts/{id} until it becomes COMPLETE or FAILED. Transcription runs off the
    request so a slow Whisper call can't time out the connection (which the browser reported
    as an opaque "Failed to fetch").
    """
    project = require_project_edit(db, project_id, user, x_workspace_token)

    if not transcription.is_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Audio transcription is not configured. Set DEEPGRAM_API_KEY, or "
                "TRANSCRIPTION_API_KEY for a hosted Whisper endpoint, or install local Whisper "
                "with `pip install -r requirements-audio.txt`."
            ),
        )

    suffix = "." + file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else ".wav"
    path = await _save_upload(file, suffix)

    on = _parse_form_date(meeting_date) or date.today()
    try:
        meeting = Meeting(
            project_id=project.id,
            title=_meeting_title(title, on),
            transcript_text="",
            meeting_date=on,
            status=MeetingStatus.PROCESSING,
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
    except BaseException:
        os.unlink(path)  # no job will run to clean it up
        raise

    background_tasks.add_task(_transcribe_and_extract, meeting.id, path)
    return meeting


@router.get("", response_model=list[MeetingListItem])
def list_meetings(
    project_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """A board's meetings, newest first, each with its task count.

    Reads only the columns the list shows, never the transcripts themselves.
    """
    require_project_view(db, project_id, user, x_workspace_token)
    columns = (Meeting.id, Meeting.project_id, Meeting.title, Meeting.meeting_date, Meeting.status,
               Meeting.error_message, Meeting.created_at)
    rows = (
        db.query(*columns, func.count(Task.id))
        .outerjoin(Task, Task.meeting_id == Meeting.id)
        .filter(Meeting.project_id == project_id)
        .group_by(*columns)
        .order_by(Meeting.created_at.desc(), Meeting.id.desc())
        .all()
    )
    return [
        MeetingListItem(id=r[0], project_id=r[1], title=r[2], meeting_date=r[3], status=r[4],
                        error_message=r[5], created_at=r[6], task_count=r[7])
        for r in rows
    ]


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(
    meeting_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Delete a meeting with every task extracted from it (and their subtasks and attachments).

    Refused while a recording is still being processed: its background job still writes to the
    meeting, so the user deletes it once it has finished (or failed).
    """
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    require_project_edit(db, meeting.project_id, user, x_workspace_token)
    if meeting.status in (MeetingStatus.PENDING, MeetingStatus.PROCESSING):
        raise HTTPException(status_code=409, detail="This meeting is still being processed. Try again when it has finished.")
    db.delete(meeting)
    db.commit()
    return Response(status_code=204)


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(
    meeting_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    require_project_view(db, meeting.project_id, user, x_workspace_token)
    return meeting


@router.patch("/{meeting_id}", response_model=MeetingOut)
def rename_meeting(
    meeting_id: int,
    payload: MeetingUpdate,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Rename a meeting. The new title is reflected on every task extracted from it."""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    require_project_edit(db, meeting.project_id, user, x_workspace_token)
    meeting.title = _meeting_title(payload.title, _anchor(meeting))
    db.commit()
    db.refresh(meeting)
    return meeting
