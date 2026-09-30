"""Per-visitor rate limits on the endpoints that cost money or invite guessing.

Parsing a transcript, uploading a recording and generating a summary or subtasks each call a
paid model API, and boards can be created without an account, so without a limit anyone could
run up the provider bill or tie up the single instance. Sign-in and password-reset requests
are limited too, against password guessing and reset-email spam. Everything else (reading
boards, editing tasks) is not limited.

Counts are kept in memory, per client address. That suits a single instance, which is how the
app is deployed; with several instances they would need a shared store such as Redis.

Behind Render's proxy every request arrives from the proxy's address, so the visitor's own
address has to come from a header, or every visitor would share one count. X-Forwarded-For is not
used: Render appends to it rather than replacing it, so its first entry is whatever the visitor
sent and could be faked to get round the limit. Render runs behind Cloudflare, which sets
CF-Connecting-IP (and True-Client-IP) to the address it received the request from, overwriting
anything the visitor sends; those are read when the RENDER variable Render sets is present.
Anywhere else the connection's own address is used and headers are ignored.

Environment variables (each limit is a count per period, e.g. "20/hour"):
    RATE_LIMITS_ENABLED   "false" turns limiting off (the test suite does this). Default on.
    RATE_LIMIT_PARSE      transcripts parsed.        Default 20/hour.
    RATE_LIMIT_AUDIO      recordings uploaded.       Default 10/hour.
    RATE_LIMIT_AI         summaries and subtask generations together. Default 30/hour.
    RATE_LIMIT_LOGIN      sign-in attempts.          Default 10/minute.
    RATE_LIMIT_RESET      password-reset requests.   Default 5/hour.
"""
from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded


# Headers holding the visitor's address, trusted only where a proxy that sets them is in front.
TRUSTED_IP_HEADERS = ("cf-connecting-ip", "true-client-ip") if os.getenv("RENDER") else ()


def client_address(request: Request) -> str:
    """The visitor's address: Cloudflare's header on Render, else the connection's own address."""
    for header in TRUSTED_IP_HEADERS:
        value = request.headers.get(header, "").strip()
        if value:
            return value
    return request.client.host if request.client else "unknown"


def _limit(name: str, default: str) -> str:
    return os.getenv(f"RATE_LIMIT_{name}", default)


PARSE = _limit("PARSE", "20/hour")
AUDIO = _limit("AUDIO", "10/hour")
AI = _limit("AI", "30/hour")
LOGIN = _limit("LOGIN", "10/minute")
RESET = _limit("RESET", "5/hour")

limiter = Limiter(
    key_func=client_address,
    enabled=os.getenv("RATE_LIMITS_ENABLED", "true").strip().lower() != "false",
)

# Summaries and subtask generation share one allowance, so neither can be used to get around
# the other's limit.
ai_limit = limiter.shared_limit(AI, scope="ai-generation",
                                error_message="You've reached the limit for AI summaries and "
                                              "subtask suggestions for now. Please try again later.")


def rate_limit_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """A 429 with a message the app can show as it is, in the same shape as every other error."""
    return JSONResponse(status_code=429, content={"detail": exc.detail})
