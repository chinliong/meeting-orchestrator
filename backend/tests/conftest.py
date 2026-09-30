"""Shared pytest fixtures: an isolated in-memory DB and a TestClient.

The LLM is never called during tests — `app.api.transcripts.TranscriptParser` is monkey-
patched per-test so the suite is fast, deterministic, and free of API keys/network.
"""
import os

# Rate limits are switched off for the suite (it signs in and parses far more often than the limits
# allow); tests/test_ratelimit.py switches them on where it checks them. Set before the app imports.
os.environ["RATE_LIMITS_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db_session():
    # A single shared in-memory SQLite connection for the duration of one test.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite ignores foreign keys unless asked; Postgres (production) always enforces them.
    # Turning them on here means a delete that would violate a foreign key fails in the tests too.
    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def background_jobs_use_the_test_db(db_session, monkeypatch):
    """Background jobs (summaries, recordings) and startup recovery open their own session; hand
    them the test session, kept open, so they never touch a real database. The summary model
    call is faked too, so no test reaches the API; tests that check summaries replace it again."""
    from app.api import transcripts as transcripts_api

    monkeypatch.setattr(transcripts_api, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr("app.llm.summary.gemini.call_tool",
                        lambda *a, **k: {"overview": "The team met and agreed the next steps."})


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def project(client):
    """A guest-created board. The client then carries its edit token, so the rest of the
    test acts as an editor of this board (the common case for task/transcript tests)."""
    resp = client.post("/api/v1/projects", json={"name": "Test Programme", "description": "x"})
    assert resp.status_code == 201
    data = resp.json()
    client.headers["X-Workspace-Token"] = data["edit_token"]
    return data


@pytest.fixture()
def account(client):
    """A registered user; returns the signup body plus a ready-to-use auth header."""
    resp = client.post("/api/v1/auth/signup", json={"email": "owner@example.com", "password": "pw123456"})
    assert resp.status_code == 201
    body = resp.json()
    body["headers"] = {"Authorization": f"Bearer {body['token']}"}
    return body
