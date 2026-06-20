"""Subtask CRUD and AI generation, with the LLM stubbed out."""
import pytest


@pytest.fixture()
def task(client, project):
    """A manually-created task on the edit-token board from the `project` fixture."""
    resp = client.post(
        "/api/v1/tasks",
        json={"project_id": project["id"], "description": "Migrate APAC payroll data"},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture()
def stub_generator(monkeypatch):
    """Replace SubtaskGenerator with a fake returning three fixed steps."""

    class FakeGenerator:
        def __init__(self, *a, **k):
            pass

        def generate(self, task, instructions=None):
            base = ["Export source records", "Map fields", "Validate in staging"]
            return [f"{instructions}: {base[0]}"] + base[1:] if instructions else base

    monkeypatch.setattr("app.api.subtasks.SubtaskGenerator", FakeGenerator)


def test_create_and_list_subtasks(client, task):
    a = client.post(f"/api/v1/tasks/{task['id']}/subtasks", json={"title": "First step"})
    assert a.status_code == 201
    assert a.json()["title"] == "First step"
    assert a.json()["done"] is False

    client.post(f"/api/v1/tasks/{task['id']}/subtasks", json={"title": "Second step"})
    listed = client.get(f"/api/v1/tasks/{task['id']}/subtasks").json()
    assert [s["title"] for s in listed] == ["First step", "Second step"]
    # Positions are assigned in insertion order.
    assert [s["position"] for s in listed] == [0, 1]


def test_blank_subtask_title_rejected(client, task):
    resp = client.post(f"/api/v1/tasks/{task['id']}/subtasks", json={"title": "   "})
    assert resp.status_code == 422


def test_task_rollup_counts_track_subtasks(client, task, project):
    s1 = client.post(f"/api/v1/tasks/{task['id']}/subtasks", json={"title": "A"}).json()
    client.post(f"/api/v1/tasks/{task['id']}/subtasks", json={"title": "B"})

    def counts():
        t = next(t for t in client.get(f"/api/v1/tasks?project_id={project['id']}").json() if t["id"] == task["id"])
        return t["subtask_total"], t["subtask_done"]

    assert counts() == (2, 0)

    # Tick one off → done count rises.
    done = client.patch(f"/api/v1/subtasks/{s1['id']}", json={"done": True})
    assert done.status_code == 200 and done.json()["done"] is True
    assert counts() == (2, 1)


def test_update_subtask_title(client, task):
    s = client.post(f"/api/v1/tasks/{task['id']}/subtasks", json={"title": "Old"}).json()
    resp = client.patch(f"/api/v1/subtasks/{s['id']}", json={"title": "New"})
    assert resp.status_code == 200 and resp.json()["title"] == "New"
    # Emptying the title is rejected.
    assert client.patch(f"/api/v1/subtasks/{s['id']}", json={"title": ""}).status_code == 422


def test_delete_subtask(client, task, project):
    s = client.post(f"/api/v1/tasks/{task['id']}/subtasks", json={"title": "Temp"}).json()
    assert client.delete(f"/api/v1/subtasks/{s['id']}").status_code == 204
    assert client.get(f"/api/v1/tasks/{task['id']}/subtasks").json() == []


def test_generate_subtasks_appends_and_returns(client, task, stub_generator):
    resp = client.post(f"/api/v1/tasks/{task['id']}/subtasks/generate", json={})
    assert resp.status_code == 201
    titles = [s["title"] for s in resp.json()]
    assert titles == ["Export source records", "Map fields", "Validate in staging"]

    # They are persisted and ordered after any existing items.
    listed = client.get(f"/api/v1/tasks/{task['id']}/subtasks").json()
    assert [s["title"] for s in listed] == titles
    assert [s["position"] for s in listed] == [0, 1, 2]


def test_generate_from_instructions_passes_them_through(client, task, stub_generator):
    resp = client.post(
        f"/api/v1/tasks/{task['id']}/subtasks/generate",
        json={"instructions": "focus on testing"},
    )
    assert resp.status_code == 201
    assert resp.json()[0]["title"].startswith("focus on testing:")


def test_generate_failure_returns_502(client, task, monkeypatch):
    class BoomGenerator:
        def __init__(self, *a, **k):
            pass

        def generate(self, *a, **k):
            raise RuntimeError("API down")

    monkeypatch.setattr("app.api.subtasks.SubtaskGenerator", BoomGenerator)
    resp = client.post(f"/api/v1/tasks/{task['id']}/subtasks/generate", json={})
    assert resp.status_code == 502
    assert "API down" in resp.json()["detail"]


def test_subtasks_respect_view_only_token(client, task, project, stub_generator):
    view_headers = {"X-Workspace-Token": project["view_token"]}
    # Reads are allowed...
    assert client.get(f"/api/v1/tasks/{task['id']}/subtasks", headers=view_headers).status_code == 200
    # ...writes and generation are not.
    blocked = client.post(
        f"/api/v1/tasks/{task['id']}/subtasks", json={"title": "x"}, headers=view_headers
    )
    assert blocked.status_code == 403
    gen = client.post(
        f"/api/v1/tasks/{task['id']}/subtasks/generate", json={}, headers=view_headers
    )
    assert gen.status_code == 403


def test_subtasks_deleted_with_task(client, task, project):
    s = client.post(f"/api/v1/tasks/{task['id']}/subtasks", json={"title": "Doomed"}).json()
    client.delete(f"/api/v1/tasks/{task['id']}")
    # The parent task is gone, so the subtask is too.
    assert client.patch(f"/api/v1/subtasks/{s['id']}", json={"done": True}).status_code == 404
