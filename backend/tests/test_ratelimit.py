"""Per-visitor rate limits (app/ratelimit.py) on the paid-API and sign-in endpoints."""
import pytest

from app.ratelimit import limiter
from app.schemas.schemas import ExtractionResult


@pytest.fixture()
def limits_on():
    """Switch limiting on with empty counts for one test; the rest of the suite runs without it."""
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


def test_sign_in_is_limited_per_visitor(client, limits_on, monkeypatch):
    # As on Render: the visitor's address comes from Cloudflare's header.
    monkeypatch.setattr("app.ratelimit.TRUSTED_IP_HEADERS", ("cf-connecting-ip", "true-client-ip"))
    body = {"email": "nobody@example.com", "password": "wrong-password"}
    me = {"CF-Connecting-IP": "198.51.100.7"}
    for _ in range(10):
        assert client.post("/api/v1/auth/login", json=body, headers=me).status_code == 401
    blocked = client.post("/api/v1/auth/login", json=body, headers=me)
    assert blocked.status_code == 429
    assert "Too many sign-in attempts" in blocked.json()["detail"]
    # A faked X-Forwarded-For does not get round the limit...
    faked = client.post("/api/v1/auth/login", json=body, headers={**me, "X-Forwarded-For": "203.0.113.9"})
    assert faked.status_code == 429
    # ...but another visitor has their own count.
    other = client.post("/api/v1/auth/login", json=body, headers={"CF-Connecting-IP": "203.0.113.9"})
    assert other.status_code == 401


def test_address_headers_are_ignored_off_render(client, limits_on):
    # Without a trusted proxy in front, a header naming a different address changes nothing.
    body = {"email": "nobody@example.com", "password": "wrong-password"}
    for _ in range(10):
        client.post("/api/v1/auth/login", json=body)
    spoofed = client.post("/api/v1/auth/login", json=body, headers={"CF-Connecting-IP": "203.0.113.50"})
    assert spoofed.status_code == 429


def test_parsing_is_limited_but_the_board_is_not(client, project, monkeypatch, limits_on):
    class FakeParser:
        def __init__(self, *a, **k):
            pass

        def parse(self, *a, **k):
            return ExtractionResult(decisions=[], action_items=[])

    monkeypatch.setattr("app.api.transcripts.TranscriptParser", FakeParser)
    payload = {"project_id": project["id"], "title": "Weekly sync", "transcript_text": "hello"}
    for _ in range(20):
        assert client.post("/api/v1/transcripts", json=payload).status_code == 201
    blocked = client.post("/api/v1/transcripts", json=payload)
    assert blocked.status_code == 429
    assert "limit for parsing transcripts" in blocked.json()["detail"]
    # Reading the board is not limited.
    assert client.get(f"/api/v1/tasks?project_id={project['id']}").status_code == 200


def test_password_reset_requests_are_limited(client, limits_on):
    for _ in range(5):
        assert client.post("/api/v1/auth/forgot-password", json={"email": "a@example.com"}).status_code == 204
    blocked = client.post("/api/v1/auth/forgot-password", json={"email": "a@example.com"})
    assert blocked.status_code == 429
    assert "password-reset requests" in blocked.json()["detail"]
