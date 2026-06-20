from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_optional_user, require_project_edit, require_project_view
from app.db import get_db
from app.llm.subtasks import SubtaskGenerator
from app.models.models import Subtask, Task, User
from app.schemas.schemas import SubtaskCreate, SubtaskGenerate, SubtaskOut, SubtaskUpdate

router = APIRouter(tags=["subtasks"])


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


def _editable_subtask(db: Session, subtask_id: int, user, ws_token) -> Subtask:
    subtask = db.get(Subtask, subtask_id)
    if subtask is None:
        raise HTTPException(status_code=404, detail="Subtask not found")
    require_project_edit(db, subtask.task.project_id, user, ws_token)
    return subtask


def _next_position(task: Task) -> int:
    return max((s.position for s in task.subtasks), default=-1) + 1


@router.get("/tasks/{task_id}/subtasks", response_model=list[SubtaskOut])
def list_subtasks(
    task_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    task = _task_for_view(db, task_id, user, x_workspace_token)
    return task.subtasks


@router.post("/tasks/{task_id}/subtasks", response_model=SubtaskOut, status_code=201)
def create_subtask(
    task_id: int,
    payload: SubtaskCreate,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    task = _task_for_edit(db, task_id, user, x_workspace_token)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Subtask title cannot be empty")
    subtask = Subtask(task_id=task.id, title=title, position=_next_position(task))
    db.add(subtask)
    db.commit()
    db.refresh(subtask)
    return subtask


@router.post("/tasks/{task_id}/subtasks/generate", response_model=list[SubtaskOut], status_code=201)
def generate_subtasks(
    task_id: int,
    payload: SubtaskGenerate,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Have the LLM break the task down and append the suggestions as new subtasks.

    Generated items are persisted immediately (the user can then delete any they don't want),
    so the response is just the newly-created subtasks.
    """
    task = _task_for_edit(db, task_id, user, x_workspace_token)
    try:
        titles = SubtaskGenerator().generate(task, payload.instructions)
    except Exception as exc:  # LLM/API failure — surface a clean error, don't 500
        raise HTTPException(status_code=502, detail=f"Could not generate subtasks: {exc}")

    if not titles:
        raise HTTPException(status_code=502, detail="The model returned no subtasks. Try again.")

    position = _next_position(task)
    created = []
    for title in titles:
        subtask = Subtask(task_id=task.id, title=title, position=position)
        position += 1
        db.add(subtask)
        created.append(subtask)
    db.commit()
    for subtask in created:
        db.refresh(subtask)
    return created


@router.patch("/subtasks/{subtask_id}", response_model=SubtaskOut)
def update_subtask(
    subtask_id: int,
    payload: SubtaskUpdate,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    subtask = _editable_subtask(db, subtask_id, user, x_workspace_token)
    data = payload.model_dump(exclude_unset=True)
    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=422, detail="Subtask title cannot be empty")
        subtask.title = title
    if "done" in data:
        subtask.done = data["done"]
    db.commit()
    db.refresh(subtask)
    return subtask


@router.delete("/subtasks/{subtask_id}", status_code=204)
def delete_subtask(
    subtask_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    subtask = _editable_subtask(db, subtask_id, user, x_workspace_token)
    db.delete(subtask)
    db.commit()
