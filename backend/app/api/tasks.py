from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.models import Task, TaskStatus
from app.schemas.schemas import TaskOut, TaskUpdate

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
    query = db.query(Task)
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
