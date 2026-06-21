from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import (
    AccessLevel,
    get_current_user,
    get_optional_user,
    project_access_level,
    require_project_edit,
    require_project_owner,
    require_project_view,
)
from app.db import get_db
from app.models.models import Project, User, _new_token
from app.schemas.schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


def project_out(project: Project, level: AccessLevel) -> ProjectOut:
    """Serialise a project for a caller, exposing the edit token only at edit level."""
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description or "",
        created_at=project.created_at,
        owner_user_id=project.owner_user_id,
        notify_enabled=project.notify_enabled,
        access_level=level,
        view_token=project.view_token,
        edit_token=project.edit_token if level == "edit" else None,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List the signed-in user's own boards. Guests reach their boards by share link."""
    projects = (
        db.query(Project)
        .filter(Project.owner_user_id == user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return [project_out(p, "edit") for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Create a board. Owned by the signed-in user, or unowned (guest) if anonymous."""
    project = Project(
        name=payload.name,
        description=payload.description,
        owner_user_id=user.id if user else None,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project_out(project, "edit")


@router.get("/by-token/{token}", response_model=ProjectOut)
def open_by_token(token: str, db: Session = Depends(get_db)):
    """Resolve a share link to the board, at the access level the token grants."""
    project = db.query(Project).filter(Project.edit_token == token).first()
    if project is not None:
        return project_out(project, "edit")
    project = db.query(Project).filter(Project.view_token == token).first()
    if project is not None:
        return project_out(project, "view")
    raise HTTPException(status_code=404, detail="Share link not found")


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    project = require_project_view(db, project_id, user, x_workspace_token)
    return project_out(project, project_access_level(project, user, x_workspace_token))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    project = require_project_edit(db, project_id, user, x_workspace_token)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project_out(project, "edit")


@router.post("/{project_id}/rotate-token", response_model=ProjectOut)
def rotate_token(
    project_id: int,
    which: Literal["view", "edit"] = Query(..., description="Which share link to regenerate"),
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Mint a fresh share token, instantly invalidating the old link of that kind.

    Owner-only: the board owner manages who can reach it. The owner reaches the board
    through their account, not the token, so rotating never locks them out.
    """
    project = require_project_owner(db, project_id, user)
    if which == "edit":
        project.edit_token = _new_token()
    else:
        project.view_token = _new_token()
    db.commit()
    db.refresh(project)
    return project_out(project, "edit")


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: int,
    user: Optional[User] = Depends(get_optional_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    project = require_project_edit(db, project_id, user, x_workspace_token)
    # Cascades to the project's meetings and tasks (configured on the relationships).
    db.delete(project)
    db.commit()
