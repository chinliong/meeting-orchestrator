"""Minimal SMTP email sender.

Provider-agnostic: point the SMTP_* env vars at any provider (Gmail, Brevo, SendGrid,
Mailgun, ...). When SMTP_HOST is unset, emails are logged instead of sent, so the
forgot-password flow stays fully testable in local dev without a provider.

Env vars:
  SMTP_HOST      e.g. smtp.gmail.com
  SMTP_PORT      587 (STARTTLS, default) or 465 (implicit SSL)
  SMTP_USER      login username (often the full from address)
  SMTP_PASSWORD  password / app password / API key
  SMTP_FROM      From address (defaults to SMTP_USER)
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("app.email")


def send_email(to: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    if not host:
        # Dev/test fallback: no provider configured, so log the message instead.
        logger.info("[email disabled] to=%s subject=%s\n%s", to, subject, body)
        return

    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "no-reply@example.com"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")

    if port == 465:
        with smtplib.SMTP_SSL(host, port) as server:
            if user and password:
                server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
