from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.auth import get_optional_user, require_project_edit, require_project_view
from app.db import get_db
from app.models.models import Meeting, Project, Task, TaskStatus, User
from app.schemas.schemas import DeletedTask, TaskCreate, TaskOut, TaskRestore, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(
    project_id: Optional[int] = None,
    owner: Optional[str] = None,
    status: Optional[TaskStatus] = None,
    due_before: Optional[date] = None,
    due_after: Optional[date] = None,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    # Eager-load the meeting so serialising `meeting_title` doesn't fire a query per task.
    query = db.query(Task).options(joinedload(Task.meeting))
    if project_id is not None:
        require_project_view(db, project_id, user, x_workspace_token)
        query = query.filter(Task.project_id == project_id)
    else:
        # No specific board: only signed-in users get a cross-board ("All projects") view,
        # scoped to the boards they own.
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in to view tasks across boards")
        owned_ids = [pid for (pid,) in db.query(Project.id).filter(Project.owner_user_id == user.id)]
        query = query.filter(Task.project_id.in_(owned_ids))
    if owner is not None:
        query = query.filter(Task.owner == owner)
    if status is not None:
        query = query.filter(Task.status == status)
    if due_before is not None:
        query = query.filter(Task.deadline <= due_before)
    if due_after is not None:
        query = query.filter(Task.deadline >= due_after)
    return query.order_by(Task.created_at.desc()).all()


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Add a task by hand — for work that wasn't captured in any meeting transcript.

    Manually-added tasks have no source meeting and carry full confidence (confidence=1.0,
    the model default), so the UI knows not to show an extraction-confidence badge for them.
    """
    require_project_edit(db, payload.project_id, user, x_workspace_token)
    task = Task(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _editable_task(db: Session, task_id: int, user, ws_token) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project_edit(db, task.project_id, user, ws_token)
    return task


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    task = _editable_task(db, task_id, user, x_workspace_token)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", response_model=DeletedTask)
def delete_task(
    task_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    task = _editable_task(db, task_id, user, x_workspace_token)
    # Snapshot the task first so the client can offer an undo (POST /tasks/restore).
    snapshot = DeletedTask(task=TaskOut.model_validate(task))
    db.delete(task)
    db.commit()
    return snapshot


@router.post("/restore", response_model=TaskOut, status_code=201)
def restore_task(
    payload: TaskRestore,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Recreate a deleted task (with its original id) from a DeletedTask snapshot. Powers undo."""
    snap = payload.task
    require_project_edit(db, snap.project_id, user, x_workspace_token)
    if db.get(Task, snap.id) is not None:
        raise HTTPException(status_code=409, detail="Task already exists")

    # Drop a dangling meeting link (e.g. the whole meeting was deleted meanwhile).
    meeting_id = snap.meeting_id if snap.meeting_id and db.get(Meeting, snap.meeting_id) else None
    task = Task(
        id=snap.id,
        project_id=snap.project_id,
        meeting_id=meeting_id,
        description=snap.description,
        owner=snap.owner,
        deadline=snap.deadline,
        status=snap.status,
        confidence=snap.confidence,
        source_decision=snap.source_decision,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task
