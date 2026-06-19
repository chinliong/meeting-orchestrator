"""HTTP trigger for the daily deadline-reminder check.

Render's free tier has no built-in scheduler, and Render Cron Jobs are a paid add-on
(no free tier). Rather than pay for that, this exposes the same check `notify_due_tasks.py`
runs as a plain HTTP endpoint that a free external scheduler (e.g. cron-job.org) can hit once
a day with a simple GET request.

There's no user session for an external pinger to present, so this is protected by a shared
secret (CRON_SECRET) instead of the usual auth/workspace tokens.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.notifications import send_due_date_notifications

router = APIRouter(prefix="/internal", tags=["internal"])


def _verify_cron_secret(secret_header: Optional[str], secret_query: Optional[str]) -> None:
    expected = os.getenv("CRON_SECRET")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured on the server")
    if (secret_header or secret_query) != expected:
        raise HTTPException(status_code=403, detail="Invalid or missing secret")


@router.get("/notify-due-tasks")
def notify_due_tasks(
    x_cron_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Run one deadline-reminder pass. Accepts the shared secret as either the
    `X-Cron-Secret` header or a `?secret=` query param, since simple free pingers often
    can't set custom headers.
    """
    _verify_cron_secret(x_cron_secret, secret)
    sent = send_due_date_notifications(db)
    return {"sent": sent}
