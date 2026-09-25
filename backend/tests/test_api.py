"""End-to-end API tests with the LLM stubbed out."""
import json
import os
import tempfile
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
    """Health reports liveness and which model extraction will actually use.

    The provider matters operationally: LLM_PROVIDER can select Gemini while the key is
    missing, and the endpoint must show the backend that would really run, not the one
    configured. It must never leak a key.
    """
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["extraction"]["provider"] in {"gemini", "anthropic", "unavailable"}
    assert "transcription" in body
    assert "key" not in json.dumps(body).lower()


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


def test_delete_account_after_password_reset_request(client, account, monkeypatch):
    # A reset request leaves a password_resets row pointing at the user. Deleting the account
    # must remove it too, or the foreign key blocks the delete (a 500 on Postgres).
    monkeypatch.setattr("app.api.auth.send_email", lambda **kw: None)
    assert client.post("/api/v1/auth/forgot-password", json={"email": "owner@example.com"}).status_code == 204

    resp = client.request("DELETE", "/api/v1/auth/me", headers=account["headers"])
    assert resp.status_code == 204
    login = client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "pw12345"})
    assert login.status_code == 401


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


def _request_reset_code(client, monkeypatch, email="owner@example.com"):
    """Trigger a reset email and return the six-digit code it carried."""
    import re

    sent = {}
    monkeypatch.setattr("app.api.auth.send_email", lambda to, subject, body: sent.update(body=body))
    assert client.post("/api/v1/auth/forgot-password", json={"email": email}).status_code == 204
    return re.search(r"\b(\d{6})\b", sent["body"]).group(1)


def test_reset_code_expires(client, db_session, account, monkeypatch):
    """An expired code is refused even when it is the right code."""
    from datetime import datetime, timedelta, timezone

    from app.models.models import PasswordReset

    code = _request_reset_code(client, monkeypatch)

    # db_session is the same session the app is using, per the client fixture.
    reset = db_session.query(PasswordReset).order_by(PasswordReset.created_at.desc()).first()
    # Stored naive-UTC, which is what the endpoint compares against.
    reset.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    db_session.commit()

    expired = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "owner@example.com", "code": code, "new_password": "fresh123"},
    )
    assert expired.status_code == 400
    # The original password still works, so nothing was changed.
    assert client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "pw12345"}).status_code == 200


def test_reset_code_burns_after_too_many_wrong_attempts(client, account, monkeypatch):
    """RESET_MAX_ATTEMPTS wrong guesses invalidate the code, so the real one stops working."""
    from app.api.auth import RESET_MAX_ATTEMPTS

    code = _request_reset_code(client, monkeypatch)
    wrong = "654321" if code != "654321" else "123456"

    for _ in range(RESET_MAX_ATTEMPTS):
        bad = client.post(
            "/api/v1/auth/reset-password",
            json={"email": "owner@example.com", "code": wrong, "new_password": "fresh123"},
        )
        assert bad.status_code == 400

    # The correct code is now dead, and the old password still stands.
    burned = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "owner@example.com", "code": code, "new_password": "fresh123"},
    )
    assert burned.status_code == 400
    assert client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "pw12345"}).status_code == 200


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


def test_owner_can_rotate_edit_token(client, account):
    created = client.post("/api/v1/projects", json={"name": "Mine"}, headers=account["headers"]).json()
    old_edit, old_view = created["edit_token"], created["view_token"]

    rotated = client.post(
        f"/api/v1/projects/{created['id']}/rotate-token?which=edit",
        headers=account["headers"],
    )
    assert rotated.status_code == 200
    body = rotated.json()
    assert body["edit_token"] != old_edit  # new link minted
    assert body["view_token"] == old_view  # the other link is untouched
    # The old edit link no longer resolves; the new one does.
    assert client.get(f"/api/v1/projects/by-token/{old_edit}").status_code == 404
    assert client.get(f"/api/v1/projects/by-token/{body['edit_token']}").status_code == 200


def test_rotate_token_is_owner_only(client, account, project):
    # A guest holding the edit link (the `project` fixture) cannot rotate it...
    assert client.post(f"/api/v1/projects/{project['id']}/rotate-token?which=edit").status_code == 403
    # ...nor can a different signed-in user who doesn't own the board.
    owned = client.post("/api/v1/projects", json={"name": "Mine"}, headers=account["headers"]).json()
    other = client.post("/api/v1/auth/signup", json={"email": "other@b.com", "password": "pw"}).json()
    blocked = client.post(
        f"/api/v1/projects/{owned['id']}/rotate-token?which=view",
        headers={"Authorization": f"Bearer {other['token']}"},
    )
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


def test_guest_board_claimed_on_login(client, account):
    guest = client.post("/api/v1/projects", json={"name": "Guest board"}).json()
    auth = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "pw12345", "claim_tokens": [guest["edit_token"]]},
    )
    assert auth.status_code == 200
    owned = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {auth.json()['token']}"}).json()
    assert [p["id"] for p in owned] == [guest["id"]]


def test_login_does_not_claim_an_owned_board(client, account):
    owned = client.post("/api/v1/projects", json={"name": "Mine"}, headers=account["headers"]).json()
    other = client.post("/api/v1/auth/signup", json={"email": "other@b.com", "password": "pw"}).json()
    client.post(
        "/api/v1/auth/login",
        json={"email": "other@b.com", "password": "pw", "claim_tokens": [owned["edit_token"]]},
    )
    theirs = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {other['token']}"}).json()
    assert theirs == []


def test_expired_token_is_rejected_not_treated_as_guest(client, account):
    """An expired login must not silently create an unowned board the user then loses."""
    import jwt
    from datetime import datetime, timedelta, timezone

    from app import auth

    expired = jwt.encode(
        {"sub": str(account["user"]["id"]), "exp": datetime.now(timezone.utc) - timedelta(days=1)},
        auth.AUTH_SECRET,
        algorithm=auth.ALGORITHM,
    )
    resp = client.post("/api/v1/projects", json={"name": "Lost?"}, headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


def test_token_of_deleted_account_is_rejected(client, account):
    client.delete("/api/v1/auth/me", headers=account["headers"])
    resp = client.post("/api/v1/projects", json={"name": "Lost?"}, headers=account["headers"])
    assert resp.status_code == 401


# --- transcripts & tasks ---

def test_list_meetings_newest_first_with_task_counts(client, project, stub_parser):
    first = client.post("/api/v1/transcripts", json={"project_id": project["id"], "title": "First", "transcript_text": "a"}).json()
    second = client.post("/api/v1/transcripts", json={"project_id": project["id"], "title": "Second", "transcript_text": "b"}).json()
    listed = client.get(f"/api/v1/transcripts?project_id={project['id']}")
    assert listed.status_code == 200
    rows = listed.json()
    assert [m["id"] for m in rows] == [second["id"], first["id"]]
    assert [m["task_count"] for m in rows] == [2, 2]
    assert "transcript_text" not in rows[0] and "tasks" not in rows[0]
    # Reading the list needs access to the board.
    anon = client.get(f"/api/v1/transcripts?project_id={project['id']}", headers={"X-Workspace-Token": ""})
    assert anon.status_code == 403


def test_delete_meeting_removes_only_its_tasks(client, project, stub_parser):
    keep = client.post("/api/v1/transcripts", json={"project_id": project["id"], "title": "Keep", "transcript_text": "a"}).json()
    drop = client.post("/api/v1/transcripts", json={"project_id": project["id"], "title": "Oops", "transcript_text": "b"}).json()
    doomed = drop["tasks"][0]["id"]
    client.post(f"/api/v1/tasks/{doomed}/subtasks", json={"title": "step"})
    client.post(f"/api/v1/tasks/{doomed}/attachments", files={"file": ("notes.txt", b"hello", "text/plain")})
    # A view link can't delete a meeting.
    view = client.delete(f"/api/v1/transcripts/{drop['id']}", headers={"X-Workspace-Token": project["view_token"]})
    assert view.status_code == 403

    assert client.delete(f"/api/v1/transcripts/{drop['id']}").status_code == 204
    remaining = client.get(f"/api/v1/tasks?project_id={project['id']}").json()
    assert {t["meeting_id"] for t in remaining} == {keep["id"]} and len(remaining) == 2
    assert client.get(f"/api/v1/transcripts/{drop['id']}").status_code == 404
    assert [m["id"] for m in client.get(f"/api/v1/transcripts?project_id={project['id']}").json()] == [keep["id"]]


def test_meeting_still_processing_cannot_be_deleted(client, project, db_session):
    from app.models.models import Meeting, MeetingStatus

    meeting = Meeting(project_id=project["id"], title="Recording", transcript_text="", status=MeetingStatus.PROCESSING)
    db_session.add(meeting)
    db_session.commit()
    resp = client.delete(f"/api/v1/transcripts/{meeting.id}")
    assert resp.status_code == 409


@pytest.fixture()
def stub_summary(monkeypatch):
    """Replace the Gemini call behind meeting summaries; records what it was sent."""
    sent = {}

    def fake_call_tool(system_prompt, tool, user_text, model=None):
        sent.update(tool=tool["name"], text=user_text)
        if "EMPTY" in user_text:
            return {"overview": "   "}
        return {"overview": "  The team reviewed the APAC mapping.  "}

    monkeypatch.setattr("app.llm.summary.gemini.call_tool", fake_call_tool)
    return sent


def test_meeting_summary_is_saved_and_listed(client, project, stub_parser, stub_summary):
    meeting = client.post("/api/v1/transcripts", json={
        "project_id": project["id"], "title": "Steering", "transcript_text": "the words", "meeting_date": "2026-06-01",
    }).json()
    assert meeting["summary"] is None
    tasks_before = client.get(f"/api/v1/tasks?project_id={project['id']}").json()

    resp = client.post(f"/api/v1/transcripts/{meeting['id']}/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary == {"overview": "The team reviewed the APAC mapping."}
    # It is made from the saved transcript, with the meeting's title and date.
    assert stub_summary["tool"] == "record_meeting_summary"
    assert "Steering" in stub_summary["text"] and "2026-06-01" in stub_summary["text"] and "the words" in stub_summary["text"]

    listed = client.get(f"/api/v1/transcripts?project_id={project['id']}").json()
    assert listed[0]["summary"] == summary
    assert client.get(f"/api/v1/transcripts/{meeting['id']}").json()["summary"] == summary
    # The tasks are neither read nor changed.
    assert client.get(f"/api/v1/tasks?project_id={project['id']}").json() == tasks_before


def test_failed_summary_leaves_the_meeting_as_it_was(client, project, stub_parser, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("HTTP 503: overloaded")

    monkeypatch.setattr("app.llm.summary.gemini.call_tool", boom)
    meeting = client.post("/api/v1/transcripts", json={"project_id": project["id"], "title": "M", "transcript_text": "x"}).json()
    resp = client.post(f"/api/v1/transcripts/{meeting['id']}/summary")
    assert resp.status_code == 502
    assert "overloaded" not in resp.json()["detail"]
    after = client.get(f"/api/v1/transcripts/{meeting['id']}").json()
    assert after["summary"] is None and after["status"] == "complete" and len(after["tasks"]) == 2


def test_summary_needs_edit_access_and_a_processed_meeting(client, project, db_session, stub_parser, stub_summary):
    from app.models.models import Meeting, MeetingStatus

    meeting = client.post("/api/v1/transcripts", json={"project_id": project["id"], "title": "M", "transcript_text": "x"}).json()
    view = client.post(f"/api/v1/transcripts/{meeting['id']}/summary", headers={"X-Workspace-Token": project["view_token"]})
    assert view.status_code == 403
    assert client.post("/api/v1/transcripts/999999/summary").status_code == 404

    recording = Meeting(project_id=project["id"], title="Recording", transcript_text="", status=MeetingStatus.PROCESSING)
    db_session.add(recording)
    db_session.commit()
    assert client.post(f"/api/v1/transcripts/{recording.id}/summary").status_code == 409
    # A blank overview from the model is a failure, not an empty summary.
    blank = client.post("/api/v1/transcripts", json={"project_id": project["id"], "title": "M", "transcript_text": "EMPTY"}).json()
    assert client.post(f"/api/v1/transcripts/{blank['id']}/summary").status_code == 502
    assert client.get(f"/api/v1/transcripts/{blank['id']}").json()["summary"] is None


def test_unreadable_stored_summary_counts_as_none(client, project, db_session, stub_parser):
    from app.models.models import Meeting

    meeting = client.post("/api/v1/transcripts", json={"project_id": project["id"], "title": "M", "transcript_text": "x"}).json()
    db_session.get(Meeting, meeting["id"]).summary = "not json"
    db_session.commit()
    assert client.get(f"/api/v1/transcripts?project_id={project['id']}").json()[0]["summary"] is None
    assert client.get(f"/api/v1/transcripts/{meeting['id']}").json()["summary"] is None


def test_duplicate_transcript_is_flagged_only_when_asked(client, project, stub_parser):
    body = {"project_id": project["id"], "title": "Weekly", "transcript_text": "same words"}
    first = client.post("/api/v1/transcripts", json=body).json()
    flagged = client.post("/api/v1/transcripts", json={**body, "check_duplicate": True})
    assert flagged.status_code == 409
    detail = flagged.json()["detail"]
    assert detail["code"] == "duplicate_transcript" and detail["meeting"]["id"] == first["id"]
    # Without the flag, or on another board, the same text is simply added.
    assert client.post("/api/v1/transcripts", json=body).status_code == 201
    other = client.post("/api/v1/projects", json={"name": "Other"}).json()
    elsewhere = client.post("/api/v1/transcripts", json={**body, "project_id": other["id"], "check_duplicate": True},
                            headers={"X-Workspace-Token": other["edit_token"]})
    assert elsewhere.status_code == 201


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


def test_same_titled_meetings_are_distinguished_by_date(client, project, stub_parser):
    """Two meetings of a series can share a title; each task carries its own meeting's date."""
    for on in ("2026-08-04", "2026-08-11"):
        client.post(
            "/api/v1/transcripts",
            json={"project_id": project["id"], "title": "Weekly SAP sync",
                  "transcript_text": "...", "meeting_date": on},
        )
    tasks = client.get(f"/api/v1/tasks?project_id={project['id']}").json()
    assert all(t["meeting_title"] == "Weekly SAP sync" for t in tasks)
    assert sorted({t["meeting_date"] for t in tasks}) == ["2026-08-04", "2026-08-11"]


def test_meeting_without_a_date_falls_back_to_its_upload_date(client, project, stub_parser,
                                                              db_session):
    """Meetings created before meeting_date existed still show a date on their tasks."""
    from app.models.models import Meeting

    meeting = client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "title": "Legacy", "transcript_text": "..."},
    ).json()
    row = db_session.get(Meeting, meeting["id"])
    row.meeting_date = None
    db_session.commit()

    tasks = client.get(f"/api/v1/tasks?project_id={project['id']}").json()
    assert all(t["meeting_date"] == row.created_at.date().isoformat() for t in tasks)


@pytest.fixture()
def capture_anchor(monkeypatch):
    """Record the meeting_date the parser is called with."""
    seen = {}
    extraction = ExtractionResult(decisions=[], action_items=[])

    class RecordingParser:
        def __init__(self, *a, **k):
            pass

        def parse(self, transcript_text, meeting_date=None):
            seen["meeting_date"] = meeting_date
            return extraction

    monkeypatch.setattr("app.api.transcripts.TranscriptParser", RecordingParser)
    return seen


def test_supplied_meeting_date_anchors_the_parse(client, project, capture_anchor):
    """A transcript of a past meeting must resolve deadlines against that meeting's date.

    Regression: the parser previously defaulted to date.today(), so the same transcript
    produced different deadlines depending on when it was uploaded.
    """
    body = client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "transcript_text": "...",
              "meeting_date": "2026-06-18"},
    ).json()
    assert capture_anchor["meeting_date"] == date(2026, 6, 18)
    assert body["meeting_date"] == "2026-06-18"


def test_meeting_date_defaults_to_today(client, project, capture_anchor):
    client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "transcript_text": "..."},
    )
    assert capture_anchor["meeting_date"] == date.today()


def test_blank_title_uses_the_supplied_meeting_date(client, project, capture_anchor):
    """The dated fallback title should name the meeting's date, not the upload date."""
    body = client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "transcript_text": "...",
              "meeting_date": "2026-06-18"},
    ).json()
    assert body["title"] == "Meeting · Jun 18, 2026"


def test_date_in_transcript_text_does_not_override_the_supplied_date(client, project,
                                                                    capture_anchor):
    """The anchor is never inferred from the transcript body.

    A date mentioned in passing - a go-live, a freeze date - must not become the anchor.
    """
    client.post(
        "/api/v1/transcripts",
        json={"project_id": project["id"], "meeting_date": "2026-06-18",
              "transcript_text": "Date: 2020-01-01\nThe freeze date is July twentieth."},
    )
    assert capture_anchor["meeting_date"] == date(2026, 6, 18)


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
    assert body["meeting_date"] is None


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

    deleted = client.delete(f"/api/v1/tasks/{task_id}")
    assert deleted.status_code == 200
    assert deleted.json()["task"]["id"] == task_id
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


def test_audio_upload_over_the_limit_is_rejected(client, project, monkeypatch):
    monkeypatch.setattr("app.api.transcripts.transcription.is_available", lambda: True)
    monkeypatch.setattr("app.api.transcripts.MAX_AUDIO_BYTES", 1024)
    resp = client.post(
        "/api/v1/transcripts/audio",
        data={"project_id": str(project["id"]), "title": "Long meeting"},
        files={"file": ("m.mp4", b"x" * 2048, "video/mp4")},
    )
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()


def test_audio_upload_reaches_transcription_as_a_file_on_disk(client, project, monkeypatch):
    # The recording is streamed to a temporary file rather than held in memory, so a large
    # video cannot exhaust the server's RAM before transcription even starts.
    captured = {}
    monkeypatch.setattr("app.api.transcripts.transcription.is_available", lambda: True)
    monkeypatch.setattr(
        "app.api.transcripts._transcribe_and_extract",
        lambda meeting_id, path: captured.update(meeting_id=meeting_id, path=path),
    )
    resp = client.post(
        "/api/v1/transcripts/audio",
        data={"project_id": str(project["id"]), "title": "Audio meeting"},
        files={"file": ("m.wav", b"audio-bytes", "audio/wav")},
    )
    assert resp.status_code == 201
    path = captured["path"]
    try:
        assert isinstance(path, str) and path.endswith(".wav")
        with open(path, "rb") as f:
            assert f.read() == b"audio-bytes"
    finally:
        os.unlink(path)


def test_background_transcription_removes_its_temp_file(client, project, db_session, monkeypatch):
    from app.api import transcripts as transcripts_api
    from app.llm.transcription import TranscriptionError
    from app.models.models import Meeting, MeetingStatus

    meeting = Meeting(project_id=project["id"], title="m", transcript_text="",
                      status=MeetingStatus.PROCESSING)
    db_session.add(meeting)
    db_session.commit()
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    def failing_transcribe(_path):
        raise TranscriptionError("provider down")

    # The job opens and closes its own session; hand it the test session and keep it open.
    monkeypatch.setattr(transcripts_api, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(transcripts_api.transcription, "transcribe_file", failing_transcribe)
    transcripts_api._transcribe_and_extract(meeting.id, path)

    assert not os.path.exists(path)
    assert meeting.status == MeetingStatus.FAILED
    assert meeting.error_message == "provider down"


def test_transcribe_audio_still_accepts_bytes(monkeypatch):
    # eval/asr_transcribe.py calls transcribe_audio(bytes); it must keep working.
    from app.llm import transcription

    seen = {}

    def fake_transcribe_file(path):
        with open(path, "rb") as f:
            seen["data"] = f.read()
        seen["path"] = path
        return "hello"

    monkeypatch.setattr(transcription, "transcribe_file", fake_transcribe_file)
    assert transcription.transcribe_audio(b"raw-bytes", suffix=".wav") == "hello"
    assert seen["data"] == b"raw-bytes"
    assert not os.path.exists(seen["path"])


# --- Undo: delete snapshot + restore -----------------------------------------------


def _make_task(client, project, description="t"):
    resp = client.post(
        "/api/v1/tasks", json={"project_id": project["id"], "description": description}
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_restore_deleted_task_round_trips(client, project):
    a = _make_task(client, project, "Renew TLS cert")
    client.patch(f"/api/v1/tasks/{a}", json={"owner": "Sam", "status": "in_progress"})

    snapshot = client.delete(f"/api/v1/tasks/{a}").json()
    assert snapshot["task"]["id"] == a
    assert client.get(f"/api/v1/tasks?project_id={project['id']}").json() == []

    restored = client.post("/api/v1/tasks/restore", json=snapshot)
    assert restored.status_code == 201
    body = restored.json()
    assert body["id"] == a  # same id is reused
    assert (body["owner"], body["status"]) == ("Sam", "in_progress")
    assert len(client.get(f"/api/v1/tasks?project_id={project['id']}").json()) == 1


def test_restore_requires_edit_access(client, project):
    a = _make_task(client, project, "A")
    snapshot = client.delete(f"/api/v1/tasks/{a}").json()

    view_headers = {"X-Workspace-Token": project["view_token"]}
    blocked = client.post("/api/v1/tasks/restore", json=snapshot, headers=view_headers)
    assert blocked.status_code == 403


# --- deadline email notifications -----------------------------------------------------


def test_notifications_default_off(client, account):
    me = client.get("/api/v1/auth/me", headers=account["headers"]).json()
    assert me["notify_email"] is False
    assert me["notify_days_before"] == 1


def test_update_notification_settings(client, account):
    resp = client.patch(
        "/api/v1/auth/notifications",
        json={"notify_email": True, "notify_days_before": 3},
        headers=account["headers"],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["notify_email"] is True
    assert body["notify_days_before"] == 3


def test_update_notification_settings_rejects_out_of_range_days(client, account):
    resp = client.patch(
        "/api/v1/auth/notifications",
        json={"notify_email": True, "notify_days_before": 99},
        headers=account["headers"],
    )
    assert resp.status_code == 422


def test_test_notification_requires_opt_in(client, account):
    resp = client.post("/api/v1/auth/notifications/test", headers=account["headers"])
    assert resp.status_code == 400


def test_test_notification_sends_when_opted_in(client, account):
    client.patch(
        "/api/v1/auth/notifications",
        json={"notify_email": True, "notify_days_before": 1},
        headers=account["headers"],
    )
    resp = client.post("/api/v1/auth/notifications/test", headers=account["headers"])
    assert resp.status_code == 200
    assert resp.json() == {"sent_tasks": 0}  # opted in, but no tasks exist yet


def test_test_notification_provider_failure_returns_clean_502(client, account, monkeypatch):
    client.patch(
        "/api/v1/auth/notifications",
        json={"notify_email": True, "notify_days_before": 1},
        headers=account["headers"],
    )
    monkeypatch.setattr(
        "app.notifications.send_email",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    resp = client.post("/api/v1/auth/notifications/test", headers=account["headers"])
    assert resp.status_code == 502


def test_project_notify_enable_toggle(client, account):
    # Reminders are opt-in: a new board starts off, and its owner can switch them on per project.
    project = client.post("/api/v1/projects", json={"name": "Mine"}, headers=account["headers"]).json()
    assert project["notify_enabled"] is False
    resp = client.patch(f"/api/v1/projects/{project['id']}", json={"notify_enabled": True}, headers=account["headers"])
    assert resp.status_code == 200
    assert resp.json()["notify_enabled"] is True


# --- internal cron-trigger endpoint -------------------------------------------------

def test_notify_due_tasks_requires_secret_configured(client, monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    resp = client.get("/api/v1/internal/notify-due-tasks")
    assert resp.status_code == 503


def test_notify_due_tasks_rejects_wrong_secret(client, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "the-real-secret")
    assert client.get("/api/v1/internal/notify-due-tasks").status_code == 403
    assert client.get("/api/v1/internal/notify-due-tasks?secret=wrong").status_code == 403


def test_notify_due_tasks_accepts_query_or_header_secret(client, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "the-real-secret")
    via_query = client.get("/api/v1/internal/notify-due-tasks?secret=the-real-secret")
    assert via_query.status_code == 200
    assert via_query.json() == {"sent": 0}

    via_header = client.get(
        "/api/v1/internal/notify-due-tasks", headers={"X-Cron-Secret": "the-real-secret"}
    )
    assert via_header.status_code == 200


# --- reminders for people a board is shared with ------------------------------------


def _second_account(client, email="friend@example.com"):
    body = client.post("/api/v1/auth/signup", json={"email": email, "password": "pw12345"}).json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_signed_in_collaborator_can_get_a_shared_boards_reminders(client, account):
    board = client.post("/api/v1/projects", json={"name": "Shared"}, headers=account["headers"]).json()
    friend = _second_account(client)
    via_view = {**friend, "X-Workspace-Token": board["view_token"]}

    assert client.get(f"/api/v1/projects/{board['id']}/reminders/me", headers=via_view).json()["subscribed"] is False
    resp = client.put(f"/api/v1/projects/{board['id']}/reminders/me", headers=via_view)
    assert resp.status_code == 200
    # Asking for a board's reminders turns on the account-wide switch.
    assert resp.json() == {"subscribed": True, "notify_email": True}
    assert client.get("/api/v1/auth/me", headers=friend).json()["notify_email"] is True
    assert client.get(f"/api/v1/projects/{board['id']}/reminders/me", headers=via_view).json()["subscribed"] is True
    assert client.get("/api/v1/auth/reminder-subscriptions", headers=friend).json() == [
        {"project_id": board["id"], "project_name": "Shared"}
    ]
    # The owner sees who gets the reminders; nobody else can.
    subs = client.get(f"/api/v1/projects/{board['id']}/subscribers", headers=account["headers"]).json()
    assert [(s["email"], s["via"]) for s in subs] == [("friend@example.com", "view")]
    assert client.get(f"/api/v1/projects/{board['id']}/subscribers", headers=via_view).status_code == 403

    assert client.delete(f"/api/v1/projects/{board['id']}/reminders/me", headers=friend).status_code == 204
    assert client.get("/api/v1/auth/reminder-subscriptions", headers=friend).json() == []


def test_shared_reminders_need_a_sign_in_access_and_an_owned_board(client, account):
    board = client.post("/api/v1/projects", json={"name": "Owned"}, headers=account["headers"]).json()
    url = f"/api/v1/projects/{board['id']}/reminders/me"
    # A guest holding the link: sign in first.
    assert client.put(url, headers={"X-Workspace-Token": board["view_token"]}).status_code == 401
    # Signed in, but without the link.
    friend = _second_account(client)
    assert client.put(url, headers=friend).status_code == 403
    # The owner uses their own settings.
    assert client.put(url, headers=account["headers"]).status_code == 409
    # A guest-created board has no owner who could revoke access.
    guest_board = client.post("/api/v1/projects", json={"name": "Guest"}).json()
    resp = client.put(f"/api/v1/projects/{guest_board['id']}/reminders/me",
                      headers={**friend, "X-Workspace-Token": guest_board["edit_token"]})
    assert resp.status_code == 409


def test_regenerating_a_link_ends_the_reminders_it_gave(client, account):
    board = client.post("/api/v1/projects", json={"name": "Shared"}, headers=account["headers"]).json()
    viewer = _second_account(client, "viewer@example.com")
    editor = _second_account(client, "editor@example.com")
    client.put(f"/api/v1/projects/{board['id']}/reminders/me", headers={**viewer, "X-Workspace-Token": board["view_token"]})
    client.put(f"/api/v1/projects/{board['id']}/reminders/me", headers={**editor, "X-Workspace-Token": board["edit_token"]})

    client.post(f"/api/v1/projects/{board['id']}/rotate-token?which=view", headers=account["headers"])
    subs = client.get(f"/api/v1/projects/{board['id']}/subscribers", headers=account["headers"]).json()
    assert [s["email"] for s in subs] == ["editor@example.com"]

    # The owner can also remove someone directly.
    editor_id = client.get("/api/v1/auth/me", headers=editor).json()["id"]
    assert client.delete(f"/api/v1/projects/{board['id']}/subscribers/{editor_id}", headers=account["headers"]).status_code == 204
    assert client.get(f"/api/v1/projects/{board['id']}/subscribers", headers=account["headers"]).json() == []


def test_deleting_tasks_boards_and_accounts_clears_shared_reminders(client, account, db_session):
    from datetime import date

    from app.models.models import ReminderSubscription, SubscriberReminder

    board = client.post("/api/v1/projects", json={"name": "Shared"}, headers=account["headers"]).json()
    friend = _second_account(client)
    client.put(f"/api/v1/projects/{board['id']}/reminders/me", headers={**friend, "X-Workspace-Token": board["view_token"]})
    task = client.post("/api/v1/tasks", json={"project_id": board["id"], "description": "t", "deadline": "2026-06-21"},
                       headers=account["headers"]).json()
    sub = db_session.query(ReminderSubscription).one()
    db_session.add(SubscriberReminder(subscription_id=sub.id, task_id=task["id"], notified_for=date(2026, 6, 21)))
    db_session.commit()

    # Deleting a task that someone was reminded about works (foreign keys are enforced).
    assert client.delete(f"/api/v1/tasks/{task['id']}", headers=account["headers"]).status_code == 200
    assert db_session.query(SubscriberReminder).count() == 0
    # Deleting the subscriber's account removes their subscription.
    assert client.delete("/api/v1/auth/me", headers=friend).status_code == 204
    assert db_session.query(ReminderSubscription).count() == 0
    # When the owner deletes their account, the board becomes a guest board: reminders stop.
    other = _second_account(client, "other@example.com")
    client.put(f"/api/v1/projects/{board['id']}/reminders/me", headers={**other, "X-Workspace-Token": board["view_token"]})
    assert client.delete("/api/v1/auth/me", headers=account["headers"]).status_code == 204
    assert db_session.query(ReminderSubscription).count() == 0
    # And a deleted board takes its subscriptions with it.
    owner2 = _second_account(client, "owner2@example.com")
    board2 = client.post("/api/v1/projects", json={"name": "B2"}, headers=owner2).json()
    client.put(f"/api/v1/projects/{board2['id']}/reminders/me", headers={**other, "X-Workspace-Token": board2["view_token"]})
    assert client.delete(f"/api/v1/projects/{board2['id']}", headers=owner2).status_code == 204
    assert db_session.query(ReminderSubscription).count() == 0
