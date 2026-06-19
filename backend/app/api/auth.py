from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db import get_db
from app.models.models import Project, User
from app.schemas.schemas import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    SignupRequest,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _claim_guest_projects(db: Session, user: User, edit_tokens: list[str]) -> None:
    """Adopt guest-created boards into a freshly registered account.

    Only unowned projects are claimable, and only via their edit token — so a viewer's
    link can never be used to seize a board.
    """
    for token in edit_tokens:
        if not token:
            continue
        project = db.query(Project).filter(Project.edit_token == token).first()
        if project is not None and project.owner_user_id is None:
            project.owner_user_id = user.id


@router.post("/signup", response_model=AuthResponse, status_code=201)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if not email or not payload.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    if db.query(User).filter(User.email == email).first() is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()  # assign user.id before claiming projects
    _claim_guest_projects(db, user, payload.claim_tokens)
    db.commit()
    db.refresh(user)
    return AuthResponse(token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return AuthResponse(token=create_access_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/password", status_code=204)
def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if not payload.new_password:
        raise HTTPException(status_code=400, detail="New password is required")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return Response(status_code=204)


@router.delete("/me", status_code=204)
def delete_account(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the account and release its boards.

    Owned projects are orphaned (owner_user_id -> None) rather than deleted, so they
    revert to guest boards still reachable by their share links — matching how
    unclaimed boards already behave.
    """
    for project in db.query(Project).filter(Project.owner_user_id == user.id).all():
        project.owner_user_id = None
    db.delete(user)
    db.commit()
    return Response(status_code=204)
