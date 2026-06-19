"""Email sender with an HTTPS API path and an SMTP fallback.

Order of preference:
  1. BREVO_API_KEY set -> send via Brevo's HTTPS API (port 443). Required on hosts that
     block outbound SMTP (e.g. Render's free tier), and the recommended production path.
  2. SMTP_HOST set -> send via SMTP. Fine for local dev or hosts that allow SMTP.
  3. neither -> log the message instead, so the flow stays testable with no provider.

Env vars:
  BREVO_API_KEY  Brevo (sendinblue) transactional API key
  SMTP_FROM      From address (must be a Brevo-verified sender; defaults to SMTP_USER)
  SMTP_HOST      e.g. smtp.gmail.com         } SMTP fallback only
  SMTP_PORT      587 (STARTTLS) or 465 (SSL) }
  SMTP_USER      login username              }
  SMTP_PASSWORD  password / app password     }
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.request
from email.message import EmailMessage

logger = logging.getLogger("app.email")


def send_email(to: str, subject: str, body: str) -> None:
    timeout = float(os.getenv("SMTP_TIMEOUT", "15"))

    api_key = os.getenv("BREVO_API_KEY")
    if api_key:
        _send_via_brevo(api_key, to, subject, body, timeout)
        return

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
        with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
            if user and password:
                server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)


def _send_via_brevo(api_key: str, to: str, subject: str, body: str, timeout: float) -> None:
    """Send a plain-text email through Brevo's transactional HTTPS API.

    The sender address must be a verified sender in the Brevo dashboard.
    """
    sender = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "no-reply@example.com"
    payload = {
        "sender": {"email": sender},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body,
    }
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode(),
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()  # drain so the connection can be reused/closed cleanly
