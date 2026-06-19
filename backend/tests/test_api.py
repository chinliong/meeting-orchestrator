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


# --- accounts ---

def test_signup_login_and_me(client):
    signup = client.post("/api/v1/auth/signup", json={"email": "a@b.com", "password": "secret1"})
    assert signup.status_code == 201
    token = signup.json()["token"]

    # Wrong password rejected; correct one works.
    assert client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "nope"}).status_code == 401
    login = client.post("/api/v1/auth/login", json={"email": "A@B.com", "password": "secret1"})
    assert login.status_code == 200

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == "a@b.com"


def test_duplicate_email_rejected(client):
    client.post("/api/v1/auth/signup", json={"email": "dup@b.com", "password": "x"})
    again = client.post("/api/v1/auth/signup", json={"email": "dup@b.com", "password": "y"})
    assert again.status_code == 409


def test_me_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_change_password(client, account):
    # Wrong current password is rejected.
    bad = client.post(
        "/api/v1/auth/password",
        json={"current_password": "wrong", "new_password": "newpw123"},
        headers=account["headers"],
    )
    assert bad.status_code == 401

    # Correct current password updates the hash.
    ok = client.post(
        "/api/v1/auth/password",
        json={"current_password": "pw12345", "new_password": "newpw123"},
        headers=account["headers"],
    )
    assert ok.status_code == 204

    # Old password no longer works; new one does.
    assert client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "pw12345"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "newpw123"}).status_code == 200


def test_change_password_requires_auth(client):
    resp = client.post("/api/v1/auth/password", json={"current_password": "a", "new_password": "b"})
    assert resp.status_code == 401


def test_delete_account_orphans_projects(client, account):
    created = client.post("/api/v1/projects", json={"name": "Keep me"}, headers=account["headers"]).json()

    resp = client.request("DELETE", "/api/v1/auth/me", headers=account["headers"])
    assert resp.status_code == 204

    # The account is gone...
    assert client.get("/api/v1/auth/me", headers=account["headers"]).status_code == 401
    # ...but the board survives and is still reachable by its share link.
    by_token = client.get(f"/api/v1/projects/by-token/{created['edit_token']}")
    assert by_token.status_code == 200 and by_token.json()["name"] == "Keep me"


def test_forgot_and_reset_password(client, account, monkeypatch):
    import re

    sent = {}
    monkeypatch.setattr("app.api.auth.send_email", lambda to, subject, body: sent.update(to=to, body=body))

    # Requesting a code always returns 204 and emails the user.
    assert client.post("/api/v1/auth/forgot-password", json={"email": "owner@example.com"}).status_code == 204
    assert sent["to"] == "owner@example.com"
    code = re.search(r"\b(\d{6})\b", sent["body"]).group(1)

    # A wrong code is rejected without resetting anything.
    wrong = "654321" if code != "654321" else "123456"
    bad = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "owner@example.com", "code": wrong, "new_password": "fresh123"},
    )
    assert bad.status_code == 400

    # The correct code sets the new password.
    ok = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "owner@example.com", "code": code, "new_password": "fresh123"},
    )
    assert ok.status_code == 204
    assert client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "fresh123"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "pw12345"}).status_code == 401

    # The code is single-use.
    reuse = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "owner@example.com", "code": code, "new_password": "again123"},
    )
    assert reuse.status_code == 400


def test_forgot_password_unknown_email_is_silent(client, monkeypatch):
    calls = []
    monkeypatch.setattr("app.api.auth.send_email", lambda **kw: calls.append(kw))
    # No account, but the response is identical (204) so existence can't be probed — and no email is sent.
    assert client.post("/api/v1/auth/forgot-password", json={"email": "nobody@nowhere.com"}).status_code == 204
    assert calls == []


# --- projects & ownership ---

def test_list_projects_is_scoped_to_owner(client, account):
    client.post("/api/v1/projects", json={"name": "Mine"}, headers=account["headers"])
    # A different user sees none of the first user's projects.
    other = client.post("/api/v1/auth/signup", json={"email": "other@b.com", "password": "pw"}).json()
    mine = client.get("/api/v1/projects", headers=account["headers"]).json()
    theirs = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {other['token']}"}).json()
    assert [p["name"] for p in mine] == ["Mine"]
    assert theirs == []


def test_create_project_exposes_tokens(client):
    body = client.post("/api/v1/projects", json={"name": "Board"}).json()
    assert body["access_level"] == "edit"
    assert body["view_token"] and body["edit_token"]
    assert body["owner_user_id"] is None  # guest-created


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
    client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "w", "transcript_text": "..."},
    )
    assert len(client.get(f"/api/v1/tasks?project_id={project['id']}").json()) == 2

    assert client.delete(f"/api/v1/projects/{project['id']}").status_code == 204
    # Project and its tasks are gone.
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 404
    assert client.get(f"/api/v1/tasks?project_id={project['id']}").status_code == 404


def test_delete_project_not_found(client):
    assert client.delete("/api/v1/projects/9999").status_code == 404


# --- share links / access control ---

def test_open_by_token_returns_level(client, project):
    edit = client.get(f"/api/v1/projects/by-token/{project['edit_token']}").json()
    assert edit["access_level"] == "edit" and edit["edit_token"]

    view = client.get(f"/api/v1/projects/by-token/{project['view_token']}").json()
    assert view["access_level"] == "view"
    assert view["edit_token"] is None  # view callers never receive the edit token


def test_view_token_is_read_only(client, project, stub_parser):
    client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "w", "transcript_text": "..."},
    )
    task_id = client.get(f"/api/v1/tasks?project_id={project['id']}").json()[0]["id"]

    view_headers = {"X-Workspace-Token": project["view_token"]}
    # Reads allowed with a view token...
    assert client.get(f"/api/v1/tasks?project_id={project['id']}", headers=view_headers).status_code == 200
    # ...writes are not.
    blocked = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "done"}, headers=view_headers)
    assert blocked.status_code == 403


def test_no_token_no_access(client):
    # A second, token-less client cannot reach a board it doesn't own.
    pid = client.post("/api/v1/projects", json={"name": "Private"}).json()["id"]
    fresh = {"X-Workspace-Token": "", "Authorization": ""}  # no credentials
    resp = client.post(
        "/api/v1/transcripts",
        json={"project_id": pid, "title": "w", "transcript_text": "..."},
        headers=fresh,
    )
    assert resp.status_code == 403


def test_guest_board_claimed_on_signup(client):
    guest = client.post("/api/v1/projects", json={"name": "Guest board"}).json()
    auth = client.post(
        "/api/v1/auth/signup",
        json={"email": "claim@b.com", "password": "pw", "claim_tokens": [guest["edit_token"]]},
    ).json()
    owned = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {auth['token']}"}).json()
    assert [p["id"] for p in owned] == [guest["id"]]


# --- transcripts & tasks ---

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
    assert body["meeting_id"] is None
    assert body["meeting_title"] is None


def test_create_task_unknown_project(client):
    resp = client.post("/api/v1/tasks", json={"project_id": 9999, "description": "x"})
    assert resp.status_code == 404


def test_rename_meeting_updates_task_titles(client, project, stub_parser):
    meeting = client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "Draft", "transcript_text": "..."},
    ).json()

    resp = client.patch(f"/api/v1/transcripts/{meeting['id']}", json={"title": "Kickoff"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Kickoff"

    tasks = client.get(f"/api/v1/tasks?project_id={project['id']}").json()
    assert all(t["meeting_title"] == "Kickoff" for t in tasks)


def test_rename_meeting_not_found(client):
    assert client.patch("/api/v1/transcripts/9999", json={"title": "x"}).status_code == 404


def test_list_tasks_across_owned_projects(client, account, stub_parser):
    h = account["headers"]
    a = client.post("/api/v1/projects", json={"name": "A"}, headers=h).json()
    b = client.post("/api/v1/projects", json={"name": "B"}, headers=h).json()
    for p in (a, b):
        client.post(
            "/api/v1/transcripts",
            json={"project_id": p["id"], "title": "w", "transcript_text": "..."},
            headers=h,
        )
    # No project_id, authenticated: tasks across every board the user owns.
    all_tasks = client.get("/api/v1/tasks", headers=h).json()
    assert {t["project_id"] for t in all_tasks} == {a["id"], b["id"]}


def test_cross_board_listing_requires_auth(client):
    assert client.get("/api/v1/tasks").status_code == 401


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
