"""End-to-end API tests with the LLM stubbed out."""
from datetime import date

import pytest

from app.schemas.schemas import ExtractedActionItem, ExtractionResult


@pytest.fixture()
def stub_parser(monkeypatch):
    """Replace TranscriptParser with a fake returning a fixed extraction."""
    extraction = ExtractionResult(
        decisions=["Move cutover to align with mapping."],
        action_items=[
            ExtractedActionItem(description="Finish APAC mapping", owner="Daniel", deadline=date(2026, 6, 19), confidence=0.95),
            ExtractedActionItem(description="Confirm cost center codes", owner="Priya", deadline=None, confidence=0.8),
        ],
    )

    class FakeParser:
        def __init__(self, *a, **k):
            pass

        def parse(self, *a, **k):
            return extraction

    monkeypatch.setattr("app.api.transcripts.TranscriptParser", FakeParser)
    return extraction


def test_health(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_create_and_list_project(client):
    client.post("/api/v1/projects", json={"name": "Alpha"})
    names = [p["name"] for p in client.get("/api/v1/projects").json()]
    assert "Alpha" in names


def test_update_project(client, project):
    resp = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"name": "Renamed", "description": "new desc"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["description"] == "new desc"


def test_update_project_not_found(client):
    assert client.patch("/api/v1/projects/9999", json={"name": "x"}).status_code == 404


def test_delete_project_cascades_tasks(client, project, stub_parser):
    # Create tasks under the project, then delete the project.
    client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "w", "transcript_text": "..."},
    )
    assert len(client.get(f"/api/v1/tasks?project_id={project['id']}").json()) == 2

    assert client.delete(f"/api/v1/projects/{project['id']}").status_code == 204
    assert client.get("/api/v1/projects").json() == []
    # Tasks were cascade-deleted with the project.
    assert client.get(f"/api/v1/tasks?project_id={project['id']}").json() == []


def test_delete_project_not_found(client):
    assert client.delete("/api/v1/projects/9999").status_code == 404


def test_submit_transcript_creates_tasks(client, project, stub_parser):
    resp = client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "Workshop 1", "transcript_text": "..."},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "complete"
    assert len(body["tasks"]) == 2

    tasks = client.get(f"/api/v1/tasks?project_id={project['id']}").json()
    assert len(tasks) == 2
    assert {t["owner"] for t in tasks} == {"Daniel", "Priya"}
    assert all(t["status"] == "todo" for t in tasks)


def test_submitted_tasks_carry_meeting_title(client, project, stub_parser):
    client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "Sprint Planning", "transcript_text": "..."},
    )
    tasks = client.get(f"/api/v1/tasks?project_id={project['id']}").json()
    assert all(t["meeting_title"] == "Sprint Planning" for t in tasks)


def test_blank_title_gets_dated_default(client, project, stub_parser):
    body = client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "transcript_text": "..."},
    ).json()
    assert body["title"].startswith("Meeting ·")


def test_create_task_manually(client, project):
    resp = client.post(
        "/api/v1/tasks",
        json={"project_id": project["id"], "description": "Renew TLS cert", "owner": "Sam"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["description"] == "Renew TLS cert"
    assert body["owner"] == "Sam"
    assert body["status"] == "todo"
    assert body["confidence"] == 1.0
    # No source meeting, so the UI shows no extraction-confidence badge.
    assert body["meeting_id"] is None
    assert body["meeting_title"] is None


def test_create_task_unknown_project(client):
    resp = client.post("/api/v1/tasks", json={"project_id": 9999, "description": "x"})
    assert resp.status_code == 404


def test_submit_transcript_unknown_project(client, stub_parser):
    resp = client.post(
        "/api/v1/transcripts",
        json={"project_id": 9999, "title": "x", "transcript_text": "y"},
    )
    assert resp.status_code == 404


def test_llm_failure_marks_meeting_failed(client, project, monkeypatch):
    class BoomParser:
        def __init__(self, *a, **k):
            pass

        def parse(self, *a, **k):
            raise RuntimeError("API down")

    monkeypatch.setattr("app.api.transcripts.TranscriptParser", BoomParser)

    resp = client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "x", "transcript_text": "y"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "failed"
    assert "API down" in body["error_message"]
    assert body["tasks"] == []


def test_task_filters(client, project, stub_parser):
    client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "w", "transcript_text": "..."},
    )
    by_owner = client.get(f"/api/v1/tasks?project_id={project['id']}&owner=Priya").json()
    assert len(by_owner) == 1 and by_owner[0]["owner"] == "Priya"

    due_filtered = client.get(f"/api/v1/tasks?project_id={project['id']}&due_before=2026-06-20").json()
    assert {t["owner"] for t in due_filtered} == {"Daniel"}  # Priya's task has no deadline


def test_update_and_delete_task(client, project, stub_parser):
    client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "w", "transcript_text": "..."},
    )
    task_id = client.get(f"/api/v1/tasks?project_id={project['id']}").json()[0]["id"]

    patched = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "in_progress"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"

    assert client.delete(f"/api/v1/tasks/{task_id}").status_code == 204
    assert client.patch(f"/api/v1/tasks/{task_id}", json={"status": "done"}).status_code == 404


def test_audio_endpoint_unavailable_without_whisper(client, project, monkeypatch):
    monkeypatch.setattr("app.api.transcripts.transcription.is_available", lambda: False)
    resp = client.post(
        "/api/v1/transcripts/audio",
        data={"project_id": str(project["id"]), "title": "Audio meeting"},
        files={"file": ("m.wav", b"fake-bytes", "audio/wav")},
    )
    assert resp.status_code == 503
    assert "whisper" in resp.json()["detail"].lower()
