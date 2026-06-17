"""Shared pytest fixtures: an isolated in-memory DB and a TestClient.

The LLM is never called during tests — `app.api.transcripts.TranscriptParser` is monkey-
patched per-test so the suite is fast, deterministic, and free of API keys/network.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    # A single shared in-memory SQLite connection for the duration of one test.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


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
    resp = client.post("/api/v1/projects", json={"name": "Test Programme", "description": "x"})
    assert resp.status_code == 201
    return resp.json()
