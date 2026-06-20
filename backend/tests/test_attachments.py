"""File attachment upload / download / delete and access control."""
import pytest

from app.api.attachments import MAX_BYTES


@pytest.fixture()
def task(client, project):
    resp = client.post(
        "/api/v1/tasks",
        json={"project_id": project["id"], "description": "Prepare go-live runbook"},
    )
    assert resp.status_code == 201
    return resp.json()


def _upload(client, task_id, name="notes.txt", content=b"hello world", ctype="text/plain", headers=None):
    return client.post(
        f"/api/v1/tasks/{task_id}/attachments",
        files={"file": (name, content, ctype)},
        headers=headers,
    )


def test_upload_list_and_download(client, task, project):
    up = _upload(client, task["id"])
    assert up.status_code == 201
    body = up.json()
    assert body["filename"] == "notes.txt"
    assert body["content_type"] == "text/plain"
    assert body["size"] == len(b"hello world")
    assert "data" not in body  # bytes are never serialised into JSON

    listed = client.get(f"/api/v1/tasks/{task['id']}/attachments").json()
    assert [a["filename"] for a in listed] == ["notes.txt"]

    dl = client.get(f"/api/v1/attachments/{body['id']}")
    assert dl.status_code == 200
    assert dl.content == b"hello world"
    assert "notes.txt" in dl.headers["content-disposition"]


def test_attachment_count_on_task(client, task, project):
    _upload(client, task["id"], name="a.txt")
    _upload(client, task["id"], name="b.txt")
    t = next(t for t in client.get(f"/api/v1/tasks?project_id={project['id']}").json() if t["id"] == task["id"])
    assert t["attachment_count"] == 2


def test_empty_upload_rejected(client, task):
    assert _upload(client, task["id"], content=b"").status_code == 400


def test_oversized_upload_rejected(client, task):
    big = b"x" * (MAX_BYTES + 1)
    assert _upload(client, task["id"], content=big).status_code == 413


def test_delete_attachment(client, task):
    body = _upload(client, task["id"]).json()
    assert client.delete(f"/api/v1/attachments/{body['id']}").status_code == 204
    assert client.get(f"/api/v1/tasks/{task['id']}/attachments").json() == []
    assert client.get(f"/api/v1/attachments/{body['id']}").status_code == 404


def test_view_token_can_read_but_not_upload(client, task, project):
    body = _upload(client, task["id"]).json()  # uploaded as editor
    view_headers = {"X-Workspace-Token": project["view_token"]}

    # View token can list and download...
    assert client.get(f"/api/v1/tasks/{task['id']}/attachments", headers=view_headers).status_code == 200
    assert client.get(f"/api/v1/attachments/{body['id']}", headers=view_headers).status_code == 200
    # ...but cannot upload or delete.
    assert _upload(client, task["id"], headers=view_headers).status_code == 403
    assert client.delete(f"/api/v1/attachments/{body['id']}", headers=view_headers).status_code == 403


def test_attachments_deleted_with_task(client, task):
    body = _upload(client, task["id"]).json()
    client.delete(f"/api/v1/tasks/{task['id']}")
    assert client.get(f"/api/v1/attachments/{body['id']}").status_code == 404
