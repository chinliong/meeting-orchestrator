from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models.models import Project, Task, TaskStatus
from app.schemas.schemas import TaskCreate, TaskOut, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(
    project_id: Optional[int] = None,
    owner: Optional[str] = None,
    status: Optional[TaskStatus] = None,
    due_before: Optional[date] = None,
    due_after: Optional[date] = None,
    db: Session = Depends(get_db),
):
    # Eager-load the meeting so serialising `meeting_title` doesn't fire a query per task.
    query = db.query(Task).options(joinedload(Task.meeting))
    if project_id is not None:
        query = query.filter(Task.project_id == project_id)
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
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    """Add a task by hand — for work that wasn't captured in any meeting transcript.

    Manually-added tasks have no source meeting and carry full confidence (confidence=1.0,
    the model default), so the UI knows not to show an extraction-confidence badge for them.
    """
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    task = Task(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)

    db.commit()
    db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
