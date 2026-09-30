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
    HTTPException,
    Header,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_optional_user, require_project_edit, require_project_view
from app.db import SessionLocal, get_db
from app.llm import summary as meeting_summary
from app.llm import transcription
from app.llm.parser import TranscriptParser
from app.models.models import (
    SUMMARY_FAILED,
    Meeting,
    MeetingStatus,
    Project,
    Task,
    User,
    is_summary_failure,
)
from app.ratelimit import AUDIO, PARSE, ai_limit, limiter
from app.schemas.schemas import (
    MeetingListItem,
    MeetingOut,
    MeetingSummary,
    MeetingUpdate,
    TranscriptSubmit,
)

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
    write_summary(meeting_id)


def write_summary(meeting_id: int) -> None:
    """Background job: write the meeting's AI summary once its tasks are saved.

    Run by the server rather than asked for by the browser, so the summary is written even if the
    user closes the page. It opens its own session (the request's is closed by then). A failure is
    recorded on the meeting rather than raised: the meeting and its tasks are already complete, and
    the summary can be written again from the board.
    """
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None or meeting.status != MeetingStatus.COMPLETE or not meeting.transcript_text.strip():
            return
        try:
            result = meeting_summary.summarise(meeting.transcript_text, meeting.title, _anchor(meeting))
        except Exception as exc:
            log.warning("summary failed for meeting %s: %s", meeting_id, exc)
            stored = SUMMARY_FAILED  # so the app can show the failure, with Try again, at once
        else:
            stored = result.model_dump_json()
        # Saved with a query, so a meeting deleted meanwhile is simply not found.
        db.query(Meeting).filter(Meeting.id == meeting_id).update(
            {Meeting.summary: stored}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def latest_meeting_id() -> int:
    """The highest meeting id so far (0 if none): taken at startup to tell older meetings apart."""
    db = SessionLocal()
    try:
        return db.query(func.max(Meeting.id)).scalar() or 0
    finally:
        db.close()


def recover_interrupted_meetings(up_to_id: int) -> int:
    """Mark meetings left processing by a restart as failed, so they can be retried or deleted.

    Processing runs inside the web process, so a restart mid-job (a deploy, a crash, the host
    moving the service) would otherwise leave the meeting "processing" for good. Only meetings up
    to `up_to_id` (the latest when this process started) are touched, so jobs this process began
    are never affected. The caller waits before running this: during a deploy Render keeps the
    old instance running for a short while after the new one starts, and a job there may still
    finish. Returns how many were marked.
    """
    db = SessionLocal()
    try:
        count = db.query(Meeting).filter(
            Meeting.id <= up_to_id,
            Meeting.status.in_([MeetingStatus.PROCESSING, MeetingStatus.PENDING]),
        ).update({Meeting.status: MeetingStatus.FAILED,
                  Meeting.error_message: "The server restarted while this meeting was being "
                                         "processed. Please add it again."},
                 synchronize_session=False)
        db.commit()
        return count
    finally:
        db.close()



@router.post("", response_model=MeetingOut, status_code=201)
@limiter.limit(PARSE, error_message="You've reached the limit for parsing transcripts for now. "
                                    "Please try again later.")
def submit_transcript(
    request: Request,
    background_tasks: BackgroundTasks,
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
    meeting = _process_transcript(project, _meeting_title(payload.title, on),
                                  payload.transcript_text, db, meeting_date=on)
    # The summary is written after the response is sent, so the tasks arrive as fast as before.
    background_tasks.add_task(write_summary, meeting.id)
    return meeting


@router.post("/audio", response_model=MeetingOut, status_code=201)
@limiter.limit(AUDIO, error_message="You've reached the limit for uploading recordings for now. "
                                    "Please try again later.")
async def submit_audio(
    request: Request,
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
               Meeting.error_message, Meeting.summary, Meeting.created_at)
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
                        error_message=r[5], summary=r[6], summary_failed=is_summary_failure(r[6]),
                        created_at=r[7], task_count=r[8])
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


@router.post("/{meeting_id}/summary", response_model=MeetingSummary)
@ai_limit
def summarise_meeting(
    request: Request,
    meeting_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Write (or rewrite) the meeting's AI summary from its saved transcript.

    A separate request from extraction: the meeting's tasks are neither read nor changed, so it
    works for meetings added before summaries existed, and a failure here leaves the meeting as
    it was.
    """
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    require_project_edit(db, meeting.project_id, user, x_workspace_token)
    if meeting.status != MeetingStatus.COMPLETE or not meeting.transcript_text.strip():
        raise HTTPException(status_code=409, detail="A meeting can be summarised once it has been processed.")
    try:
        result = meeting_summary.summarise(meeting.transcript_text, meeting.title, _anchor(meeting))
    except Exception as exc:  # LLM/API failure: a clean error, and the meeting is untouched
        log.warning("summary failed for meeting %s: %s", meeting.id, exc)
        raise HTTPException(status_code=502, detail="Could not write a summary right now. Please try again.")
    # Saved with a query rather than on the loaded row, so a meeting deleted while its summary was
    # being written is simply not found instead of failing the save.
    saved = db.query(Meeting).filter(Meeting.id == meeting_id).update(
        {Meeting.summary: result.model_dump_json()}, synchronize_session=False)
    db.commit()
    if not saved:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return result


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
