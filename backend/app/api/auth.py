import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, verify_password
from app.db import get_db
from app.email import send_email
from app.models.models import PasswordReset, Project, User
from app.notifications import send_test_notification
from app.schemas.schemas import (
    AuthResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    NotificationSettingsUpdate,
    ResetPasswordRequest,
    SignupRequest,
    UserOut,
)

logger = logging.getLogger("app.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_CODE_TTL = timedelta(minutes=15)
RESET_MAX_ATTEMPTS = 5


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


@router.patch("/notifications", response_model=UserOut)
def update_notifications(
    payload: NotificationSettingsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.notify_email = payload.notify_email
    user.notify_days_before = payload.notify_days_before
    db.commit()
    db.refresh(user)
    return user


@router.post("/notifications/test", status_code=200)
def send_test_notification_email(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.notify_email:
        raise HTTPException(status_code=400, detail="Enable email notifications first")
    sent_tasks = send_test_notification(db, user)
    return {"sent_tasks": sent_tasks}


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


def _send_reset_email(to: str, code: str) -> None:
    """Send a reset code, swallowing errors so a flaky SMTP host never surfaces to callers."""
    try:
        send_email(
            to=to,
            subject="Your password reset code",
            body=(
                f"Your password reset code is {code}\n\n"
                "It expires in 15 minutes. If you didn't request this, you can ignore this email."
            ),
        )
    except Exception:
        logger.exception("Failed to send password reset email")


@router.post("/forgot-password", status_code=204)
def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Email a 6-digit reset code.

    Always returns 204 regardless of whether the email exists, so the endpoint can't be
    used to discover which addresses have accounts. The email is sent in the background so
    a slow SMTP handshake doesn't hold the request open.
    """
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is not None:
        # Invalidate any earlier outstanding codes so only the newest one works.
        db.query(PasswordReset).filter(
            PasswordReset.user_id == user.id, PasswordReset.used.is_(False)
        ).update({PasswordReset.used: True})

        code = f"{secrets.randbelow(1_000_000):06d}"
        db.add(
            PasswordReset(
                user_id=user.id,
                code_hash=hash_password(code),
                expires_at=datetime.now(timezone.utc) + RESET_CODE_TTL,
            )
        )
        db.commit()
        background_tasks.add_task(_send_reset_email, user.email, code)

    return Response(status_code=204)


@router.post("/reset-password", status_code=204)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if not payload.new_password:
        raise HTTPException(status_code=400, detail="New password is required")

    invalid = HTTPException(status_code=400, detail="Invalid or expired code")
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise invalid

    reset = (
        db.query(PasswordReset)
        .filter(PasswordReset.user_id == user.id, PasswordReset.used.is_(False))
        .order_by(PasswordReset.created_at.desc())
        .first()
    )
    # Stored datetimes are naive UTC; compare against a naive now.
    if reset is None or reset.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        raise invalid

    if not verify_password(payload.code, reset.code_hash):
        reset.attempts += 1
        if reset.attempts >= RESET_MAX_ATTEMPTS:
            reset.used = True  # too many guesses — burn the code
        db.commit()
        raise invalid

    user.password_hash = hash_password(payload.new_password)
    reset.used = True
    db.commit()
    return Response(status_code=204)
