from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Header, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth import get_optional_user, require_project_edit, require_project_view
from app.db import get_db
from app.models.models import Attachment, Task, User
from app.schemas.schemas import AttachmentOut

router = APIRouter(tags=["attachments"])

# Attachment bytes live in the database (see app/models/models.Attachment), so keep them small.
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


def _task_for_view(db: Session, task_id: int, user, ws_token) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project_view(db, task.project_id, user, ws_token)
    return task


def _task_for_edit(db: Session, task_id: int, user, ws_token) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project_edit(db, task.project_id, user, ws_token)
    return task


def _attachment_for_view(db: Session, attachment_id: int, user, ws_token) -> Attachment:
    att = db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    require_project_view(db, att.task.project_id, user, ws_token)
    return att


@router.get("/tasks/{task_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(
    task_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    task = _task_for_view(db, task_id, user, x_workspace_token)
    return task.attachments


@router.post("/tasks/{task_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    task_id: int,
    file: UploadFile = File(...),
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    task = _task_for_edit(db, task_id, user, x_workspace_token)

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large. The limit is {MAX_BYTES // (1024 * 1024)} MB.",
        )

    attachment = Attachment(
        task_id=task.id,
        filename=(file.filename or "file").strip() or "file",
        content_type=file.content_type or "application/octet-stream",
        size=len(data),
        data=data,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/attachments/{attachment_id}")
def download_attachment(
    attachment_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    att = _attachment_for_view(db, attachment_id, user, x_workspace_token)
    # RFC 5987 filename* keeps non-ASCII names intact; the request is authorised via the same
    # header/token machinery as every other read, so the browser fetches this with JS.
    disposition = f"attachment; filename*=UTF-8''{quote(att.filename)}"
    return Response(
        content=att.data,
        media_type=att.content_type,
        headers={"Content-Disposition": disposition},
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(
    attachment_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    att = db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    require_project_edit(db, att.task.project_id, user, x_workspace_token)
    db.delete(att)
    db.commit()
