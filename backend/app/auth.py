"""Authentication and per-workspace access control.

The app is multi-tenant via two mechanisms that an endpoint can accept together:

- **Accounts** — an `Authorization: Bearer <jwt>` identifies a logged-in user, who owns
  the projects they create.
- **Capability links** — an `X-Workspace-Token` header carries a project's permanent
  share token. Holding an edit token grants write access; a view token grants read-only.
  This is how guests and link recipients reach a board without an account.

`project_access_level()` collapses both into "edit" / "view" / None for a given project.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import jwt
from fastapi import Depends, Header, HTTPException
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.models import Project, User

AUTH_SECRET = os.getenv("AUTH_SECRET", "dev-insecure-secret-change-me")
ALGORITHM = "HS256"
TOKEN_TTL = timedelta(days=30)

# bcrypt has a 72-byte input cap; passlib handles truncation/identification for us.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

AccessLevel = Literal["edit", "view"]


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": datetime.now(timezone.utc) + TOKEN_TTL}
    return jwt.encode(payload, AUTH_SECRET, algorithm=ALGORITHM)


def _decode_user_id(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def get_optional_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Resolve the bearer token to a user, or None for anonymous/guest requests."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    user_id = _decode_user_id(authorization.split(" ", 1)[1].strip())
    if user_id is None:
        return None
    return db.get(User, user_id)


def get_current_user(user: Optional[User] = Depends(get_optional_user)) -> User:
    """Require a logged-in user (used for account-only routes like 'my projects')."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def project_access_level(
    project: Project, user: Optional[User], ws_token: Optional[str]
) -> Optional[AccessLevel]:
    if user is not None and project.owner_user_id == user.id:
        return "edit"
    if ws_token:
        if ws_token == project.edit_token:
            return "edit"
        if ws_token == project.view_token:
            return "view"
    return None


def _load_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def require_project_view(
    db: Session, project_id: int, user: Optional[User], ws_token: Optional[str]
) -> Project:
    project = _load_project(db, project_id)
    if project_access_level(project, user, ws_token) is None:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    return project


def require_project_edit(
    db: Session, project_id: int, user: Optional[User], ws_token: Optional[str]
) -> Project:
    project = _load_project(db, project_id)
    if project_access_level(project, user, ws_token) != "edit":
        raise HTTPException(status_code=403, detail="This share link is view-only")
    return project


def require_project_owner(db: Session, project_id: int, user: Optional[User]) -> Project:
    """Require the signed-in account that owns the board.

    Stricter than edit access: a guest holding the edit link can change tasks but
    can't manage the share links themselves. Guest-created boards (no owner) have
    nobody who can pass this gate — they're unmanaged by design.
    """
    project = _load_project(db, project_id)
    if user is None or project.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the board owner can do this")
    return project
