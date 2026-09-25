from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
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
from app.models.models import Project, ReminderSubscription, User, _new_token
from app.schemas.schemas import (
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ReminderSubscriptionState,
    SubscriberOut,
)

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
    changes = payload.model_dump(exclude_unset=True)
    if "notify_enabled" in changes:
        # Reminders for a board are emailed to its owner alone, so only the owner decides whether
        # they are sent; an edit-link holder can change the board but not the owner's reminders.
        require_project_owner(db, project_id, user)
    for field, value in changes.items():
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
    # Whoever asked for reminders through the old link has just lost access, so their
    # reminders stop too; otherwise the board's tasks would keep reaching them by email.
    for sub in list(project.reminder_subscriptions):
        if sub.via == which:
            db.delete(sub)
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


# --- reminders for people a board is shared with ---


def _subscription(db: Session, project_id: int, user_id: int) -> Optional[ReminderSubscription]:
    return (
        db.query(ReminderSubscription)
        .filter(ReminderSubscription.project_id == project_id, ReminderSubscription.user_id == user_id)
        .first()
    )


@router.get("/{project_id}/reminders/me", response_model=ReminderSubscriptionState)
def get_my_reminders(
    project_id: int,
    user: User = Depends(get_current_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Whether the signed-in user gets this shared board's reminders."""
    require_project_view(db, project_id, user, x_workspace_token)
    return ReminderSubscriptionState(
        subscribed=_subscription(db, project_id, user.id) is not None, notify_email=user.notify_email
    )


@router.put("/{project_id}/reminders/me", response_model=ReminderSubscriptionState)
def subscribe_to_reminders(
    project_id: int,
    user: User = Depends(get_current_user),
    x_workspace_token: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Ask for the deadline reminders of a board shared with you.

    Needs a sign-in (reminders go to a confirmed account, never to a typed-in address) and the
    board's share link. Only boards with an owner qualify: the owner can revoke access by
    regenerating the link, which also ends these reminders. Asking for a board's reminders
    turns on the account-wide reminders switch, since that is what the user asked for.
    """
    project = require_project_view(db, project_id, user, x_workspace_token)
    if project.owner_user_id == user.id:
        raise HTTPException(status_code=409, detail="This is your board. Turn its reminders on in Account settings.")
    if project.owner_user_id is None:
        raise HTTPException(status_code=409, detail="Reminders are available on boards saved to an account.")
    via = "edit" if x_workspace_token == project.edit_token else "view"
    sub = _subscription(db, project_id, user.id)
    if sub is None:
        db.add(ReminderSubscription(project_id=project.id, user_id=user.id, via=via))
    else:
        sub.via = via
    user.notify_email = True
    db.commit()
    return ReminderSubscriptionState(subscribed=True, notify_email=True)


@router.delete("/{project_id}/reminders/me", status_code=204)
def unsubscribe_from_reminders(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stop a shared board's reminders. Always allowed, even after losing access to the board."""
    sub = _subscription(db, project_id, user.id)
    if sub is not None:
        db.delete(sub)
        db.commit()
    return Response(status_code=204)


@router.get("/{project_id}/subscribers", response_model=list[SubscriberOut])
def list_subscribers(
    project_id: int,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Owner-only: the people who asked for this board's reminders."""
    project = require_project_owner(db, project_id, user)
    subs = sorted(project.reminder_subscriptions, key=lambda sub: sub.id)
    return [
        SubscriberOut(user_id=sub.user_id, email=sub.user.email, via=sub.via, created_at=sub.created_at)
        for sub in subs
    ]


@router.delete("/{project_id}/subscribers/{subscriber_id}", status_code=204)
def remove_subscriber(
    project_id: int,
    subscriber_id: int,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    """Owner-only: stop someone's reminders for this board. Their link access is unchanged."""
    require_project_owner(db, project_id, user)
    sub = _subscription(db, project_id, subscriber_id)
    if sub is not None:
        db.delete(sub)
        db.commit()
    return Response(status_code=204)
