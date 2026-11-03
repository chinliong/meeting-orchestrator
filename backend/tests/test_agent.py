"""Agent contract, access, evidence and transactional approval tests. No model API calls."""
import copy
import json
from datetime import date, datetime, timedelta

import pytest

from app.api import agent as agent_api
from app.llm import agent
from app.models.models import AgentReview, Attachment, Meeting, MeetingStatus, Task, TaskStatus
from app.schemas.agent import ReviewInput


TRANSCRIPT = "Alex: The landing page design is now finished and approved. Sam: I will write the release notes by 5 November 2026."
INPUT = {"title": "Follow-up", "meeting_date": "2026-11-02", "transcript": TRANSCRIPT}


REAL_EXTRACT_CANDIDATES = agent_api.extract_candidates

# What the faked parser extracts from TRANSCRIPT: the one new commitment in it.
CANDIDATES = [{"description": "Write the release notes", "owner": "Sam", "deadline": "2026-11-05",
               "status": "todo", "confidence": 0.9, "source_decision": "Sam committed to the release notes."}]


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(agent_api, "write_summary", lambda meeting_id: None)
    monkeypatch.setattr(agent_api, "extract_candidates", lambda payload: copy.deepcopy(CANDIDATES))
    monkeypatch.setenv("ENABLE_MEETING_AGENT", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "existing-flash-model")


@pytest.fixture
def task(db_session, project):
    t = Task(project_id=project["id"], description="Finish the landing page design", owner="Alex",
             deadline=date(2026, 11, 4), status=TaskStatus.IN_PROGRESS)
    db_session.add(t)
    db_session.commit()
    return t


def plan_for(task_id):
    return {"summary": "One completed task and one new action.", "questions": [], "proposals": [
        {"kind": "update", "task_id": task_id,
         "after": {"description": "Finish the landing page design", "owner": "Alex",
                   "deadline": "2026-11-04", "status": "done"},
         "evidence": "The landing page design is now finished and approved.", "reason": "Alex confirmed completion."},
        {"kind": "create", "task_id": None,
         "after": {"description": "Write the release notes", "owner": "Sam",
                   "deadline": "2026-11-05", "status": "todo"},
         "evidence": "Sam: I will write the release notes by 5 November 2026.", "reason": "A new commitment."},
    ]}


def call(name, args=None, signature=None):
    part = {"functionCall": {"name": name, "args": args or {}, "id": "call-1"}}
    if signature:
        part["thoughtSignature"] = signature
    return {"role": "model", "parts": [part]}


def fake_model(monkeypatch, plan):
    calls = []
    def turn(contents, allowed, model, timeout):
        calls.append(copy.deepcopy(contents))
        assert model == "existing-flash-model"
        assert 0 < timeout <= 90
        assert "read_board" not in allowed  # the board is sent with the request
        return call("finish_review", plan)
    monkeypatch.setattr(agent, "model_turn", turn)
    return calls


def create(client, project):
    return client.post(f"/api/v1/projects/{project['id']}/agent/reviews", json=INPUT)


def route(project, review, suffix=""):
    return f"/api/v1/projects/{project['id']}/agent/reviews/{review['id']}{suffix}"


def test_disabled_by_default(client, project, monkeypatch):
    monkeypatch.delenv("ENABLE_MEETING_AGENT", raising=False)
    assert create(client, project).status_code == 404
    assert client.get("/api/v1/health").json()["features"]["meeting_agent"] is False


def test_no_key_does_not_fall_back_to_another_provider(client, project, enabled, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    assert create(client, project).status_code == 503


def test_review_is_read_only_and_preserves_signatures(client, project, task, enabled, monkeypatch, db_session):
    calls = []
    turns = iter([call("read_meeting", {"meeting_id": 999}, signature="signature-must-survive"),
                  call("finish_review", plan_for(task.id))])
    def turn(contents, allowed, model, timeout):
        calls.append(copy.deepcopy(contents))
        return next(turns)
    monkeypatch.setattr(agent, "model_turn", turn)
    response = create(client, project)
    assert response.status_code == 201, response.text
    review = response.json()
    assert review["model"] == "existing-flash-model"
    assert review["proposals"][0]["before"]["status"] == "in_progress"
    assert calls[1][1]["parts"][0]["thoughtSignature"] == "signature-must-survive"
    assert calls[1][2]["parts"][0]["functionResponse"]["id"] == "call-1"
    db_session.refresh(task)
    assert task.status == TaskStatus.IN_PROGRESS
    assert db_session.query(Task).count() == 1
    assert db_session.query(Meeting).count() == 0
    assert len(client.get(f"/api/v1/projects/{project['id']}/agent/reviews").json()) == 1


def test_apply_selected_only_and_idempotent(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    url = route(project, review, "/apply")
    response = client.post(url, json={"proposal_ids": [0]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "applied"
    assert db_session.query(Task).count() == 1
    assert db_session.query(Meeting).count() == 1
    db_session.refresh(task)
    assert task.status == TaskStatus.DONE
    assert task.meeting_id is None  # Original task provenance is preserved.
    assert client.post(url, json={"proposal_ids": [0]}).status_code == 200
    assert db_session.query(Meeting).count() == 1
    assert client.post(url, json={"proposal_ids": [1]}).status_code == 409


def test_apply_and_undo_restore_board(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    response = client.post(route(project, review, "/apply"), json={"proposal_ids": [0, 1]})
    assert response.status_code == 200, response.text
    assert db_session.query(Task).count() == 2
    undo = client.post(route(project, review, "/undo"))
    assert undo.status_code == 200, undo.text
    db_session.refresh(task)
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.deadline == date(2026, 11, 4)
    assert db_session.query(Task).count() == 1
    assert db_session.query(Meeting).count() == 0
    assert client.post(route(project, review, "/undo")).status_code == 200
    assert client.post(route(project, review, "/apply"), json={"proposal_ids": [0]}).status_code == 409


def test_stale_board_rejected_atomically(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    task.owner = "New owner"
    db_session.commit()
    response = client.post(route(project, review, "/apply"), json={"proposal_ids": [0, 1]})
    assert response.status_code == 409
    assert db_session.query(Meeting).count() == 0
    assert db_session.get(AgentReview, review["id"]).status == "draft"
    assert db_session.get(Task, task.id).owner == "New owner"


def test_added_task_also_invalidates_baseline(client, project, task, enabled, monkeypatch):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    client.post("/api/v1/tasks", json={"project_id": project["id"], "description": "Write the release notes"})
    assert client.post(route(project, review, "/apply"), json={"proposal_ids": [1]}).status_code == 409


def test_undo_protects_newer_edits_and_attachments(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    client.post(route(project, review, "/apply"), json={"proposal_ids": [0, 1]})
    new_task = db_session.query(Task).filter(Task.id != task.id).one()
    db_session.add(Attachment(task_id=new_task.id, filename="notes.txt", content_type="text/plain", size=1, data=b"x"))
    db_session.commit()
    response = client.post(route(project, review, "/undo"))
    assert response.status_code == 409
    assert db_session.query(Attachment).count() == 1
    assert db_session.get(AgentReview, review["id"]).status == "applied"


@pytest.mark.parametrize("selection", [[99], [0, 0], [True], ["0"]])
def test_invalid_selection_rejected(client, project, task, enabled, monkeypatch, selection):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    assert client.post(route(project, review, "/apply"), json={"proposal_ids": selection}).status_code == 422


def test_expiry_and_client_patch_tampering(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    url = route(project, review, "/apply")
    assert client.post(url, json={"proposal_ids": [0], "after": {"owner": "attacker"}}).status_code == 422
    row = db_session.get(AgentReview, review["id"])
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert client.post(url, json={"proposal_ids": [0]}).status_code == 409


def test_viewers_and_other_boards_cannot_review_or_apply(client, project, task, enabled, monkeypatch):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    client.headers["X-Workspace-Token"] = project["view_token"]
    assert create(client, project).status_code == 403
    assert client.get(route(project, review)).status_code == 403
    assert client.post(route(project, review, "/apply"), json={"proposal_ids": [0]}).status_code == 403
    other = client.post("/api/v1/projects", json={"name": "Other"}).json()
    client.headers["X-Workspace-Token"] = other["edit_token"]
    assert client.get(route(other, review)).status_code == 404
    assert client.get(route(project, review)).status_code == 403


@pytest.mark.parametrize("bad", ["quote", "target", "no_op", "date"])
def test_invalid_model_output_never_reaches_board(client, project, task, enabled, monkeypatch, db_session, bad):
    plan = plan_for(task.id)
    if bad == "quote":
        plan["proposals"][0]["evidence"] = "This sentence was invented by the model."
    elif bad == "target":
        plan["proposals"][0]["task_id"] = 9999
    elif bad == "no_op":
        plan["proposals"][0]["after"]["status"] = "in_progress"
    elif bad == "duplicate":
        plan["proposals"][1]["after"]["description"] = task.description
    elif bad == "date":
        plan["proposals"][1]["after"]["deadline"] = "next Thursday"
    calls = fake_model(monkeypatch, plan)
    response = create(client, project)
    assert response.status_code == 502, response.text
    assert len(calls) == agent.MAX_STEPS
    assert db_session.query(AgentReview).count() == 0
    assert db_session.query(Task).count() == 1


def test_correction_can_recover_invalid_evidence(client, project, task, enabled, monkeypatch):
    good = plan_for(task.id)
    bad = copy.deepcopy(good)
    bad["proposals"][0]["evidence"] = "An invented quote that must be corrected."
    responses = iter([call("finish_review", bad), call("finish_review", good)])
    monkeypatch.setattr(agent, "model_turn", lambda *a: next(responses))
    response = create(client, project)
    assert response.status_code == 201
    assert response.json()["steps"] == 2


def test_earlier_meeting_cannot_roll_back_newer_work(client, project, task, enabled, monkeypatch, db_session):
    meeting = Meeting(project_id=project["id"], title="Later meeting", transcript_text="Later context",
                      meeting_date=date(2026, 11, 3), status=MeetingStatus.COMPLETE)
    db_session.add(meeting)
    db_session.flush()
    task.meeting_id = meeting.id
    db_session.commit()
    fake_model(monkeypatch, plan_for(task.id))
    assert create(client, project).status_code == 502


def test_duplicate_transcript_not_imported_again(client, project, task, enabled, monkeypatch):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    client.post(route(project, review, "/apply"), json={"proposal_ids": [0]})
    assert create(client, project).status_code == 409


def test_undo_update_only_review_protects_renamed_meeting(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    applied = client.post(route(project, review, "/apply"), json={"proposal_ids": [0]}).json()
    meeting = db_session.get(Meeting, applied["receipt"]["meeting_id"])
    meeting.title = "Renamed after review"
    db_session.commit()
    response = client.post(route(project, review, "/undo"))
    assert response.status_code == 409
    db_session.refresh(task)
    assert task.status == TaskStatus.DONE  # The earlier restoration in the transaction rolled back.
    assert db_session.get(AgentReview, review["id"]).status == "applied"


def test_read_tools_are_scoped_and_unknown_tools_cannot_execute(monkeypatch):
    turns = iter([call("read_board"), call("read_meeting", {"meeting_id": 99}),
                  call("delete_project", {"project_id": 1}),
                  call("finish_review", {"summary": "Needs clarification.", "proposals": [], "questions": ["Which task?"]})])
    captured = []
    def turn(contents, *args):
        captured.append(copy.deepcopy(contents))
        return next(turns)
    monkeypatch.setattr(agent, "model_turn", turn)
    result = agent.run_review(ReviewInput(**INPUT), {"tasks": []}, {})
    assert result["proposals"] == []
    assert "not available at this step" in json.dumps(captured[1])  # the board is sent, not fetched
    assert "not available in this project" in json.dumps(captured[2])
    assert "not available at this step" in json.dumps(captured[3])


def test_read_source_meeting_and_empty_review(monkeypatch):
    turns = iter([call("read_meeting", {"meeting_id": 7}),
                  call("finish_review", {"summary": "Already reflected on the board.", "proposals": [], "questions": []})])
    monkeypatch.setattr(agent, "model_turn", lambda *a: next(turns))
    result = agent.run_review(ReviewInput(**INPUT), {"tasks": []}, {7: {"title": "Earlier planning", "transcript": "Context"}})
    assert any("Earlier planning" in t["label"] for t in result["trace"])
    assert result["proposals"] == []


def test_recent_update_only_meetings_are_available_to_agent(client, project, task, enabled, monkeypatch, db_session):
    meeting = Meeting(project_id=project["id"], title="Follow-up without new tasks",
                      transcript_text="Earlier decisions remain useful context.",
                      meeting_date=date(2026, 11, 1), status=MeetingStatus.COMPLETE)
    db_session.add(meeting)
    db_session.commit()
    meeting_id = meeting.id
    calls = fake_model(monkeypatch, plan_for(task.id))
    assert create(client, project).status_code == 201
    board = json.loads(calls[0][0]["parts"][0]["text"])["board"]  # sent with the request
    assert any(m["id"] == meeting_id for m in board["meetings"])
    assert "Earlier decisions remain useful" not in json.dumps(board)  # Full text is retrieved on demand.


@pytest.mark.parametrize("with_suggestions", [False, True])
def test_save_meeting_without_task_changes(client, project, task, enabled, monkeypatch, db_session, with_suggestions):
    plan = plan_for(task.id) if with_suggestions else {"summary": "Discussion only.", "questions": [], "proposals": []}
    fake_model(monkeypatch, plan)
    review = create(client, project).json()
    url = route(project, review, "/apply")
    result = client.post(url, json={"proposal_ids": []})
    assert result.status_code == 200, result.text
    assert result.json()["receipt"]["proposal_ids"] == []
    assert db_session.query(Meeting).count() == 1
    db_session.refresh(task)
    assert task.status == TaskStatus.IN_PROGRESS
    assert db_session.query(Task).count() == 1
    assert client.post(url, json={"proposal_ids": []}).status_code == 200
    assert db_session.query(Meeting).count() == 1
    assert client.post(route(project, review, "/undo")).status_code == 200
    assert db_session.query(Meeting).count() == 0
    assert db_session.query(Task).count() == 1


def parse_with_assistant(client, project):
    return client.post(f"/api/v1/projects/{project['id']}/agent/parse", json=INPUT)


@pytest.mark.parametrize("kind", ["create", "none", "mixed", "update", "matched"])
def test_parse_saves_new_work_but_requires_confirmation_for_updates(client, project, task, enabled, monkeypatch, db_session, kind):
    plan = plan_for(task.id)
    if kind == "create":
        plan["proposals"] = plan["proposals"][1:]
    elif kind == "update":
        plan["proposals"] = plan["proposals"][:1]
    elif kind in ("none", "matched"):
        plan["proposals"] = []
    if kind == "matched":
        # The assistant recognises the parser's candidate as the existing task.
        plan["existing_items"] = [{"item": 0, "task_id": task.id}]
    fake_model(monkeypatch, plan)
    response = parse_with_assistant(client, project)
    assert response.status_code == 201, response.text
    data = response.json()
    assert db_session.query(Meeting).count() == 1
    assert data["meeting_id"] is not None
    db_session.refresh(task)
    assert task.status == TaskStatus.IN_PROGRESS
    # The parser's candidate is new work unless the assistant matched it to an existing task.
    expected_new = int(kind != "matched")
    assert data["new_task_count"] == expected_new
    assert db_session.query(Task).count() == 1 + expected_new
    if kind in ("mixed", "update"):
        review = data["review"]
        assert review["mode"] == "meeting_updates"
        assert all(p["kind"] == "update" for p in review["proposals"])
        applied = client.post(route(project, review, "/apply"), json={"proposal_ids": [p["id"] for p in review["proposals"]]})
        assert applied.status_code == 200, applied.text
        assert applied.json()["receipt"]["meeting_id"] is None
        db_session.refresh(task)
        assert task.status == TaskStatus.DONE
        assert db_session.query(Meeting).count() == 1
        assert client.post(route(project, review, "/undo")).status_code == 200
        db_session.refresh(task)
        assert task.status == TaskStatus.IN_PROGRESS
        assert db_session.query(Meeting).count() == 1
        assert db_session.query(Task).count() == 1 + expected_new
    elif kind == "matched":
        # The matched task waits, unticked, as a possible duplicate rather than being dropped.
        review = data["review"]
        assert [(p["kind"], p["possible_duplicate"], p["duplicate_of"]["id"]) for p in review["proposals"]] == [("create", True, task.id)]
    else:
        assert data["review"] is None
    # A retry cannot duplicate the imported meeting or its new tasks.
    assert parse_with_assistant(client, project).status_code == 409
    assert db_session.query(Meeting).count() == 1


def test_parse_rolls_back_import_if_pending_review_cannot_be_saved(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    from sqlalchemy import event
    def fail_pending(mapper, connection, target):
        if json.loads(target.plan_json).get("mode") == "meeting_updates":
            raise RuntimeError("Simulated storage failure")
    event.listen(AgentReview, "before_insert", fail_pending)
    try:
        with pytest.raises(RuntimeError, match="Simulated storage failure"):
            parse_with_assistant(client, project)
    finally:
        event.remove(AgentReview, "before_insert", fail_pending)
        db_session.rollback()
    assert db_session.query(Meeting).count() == 0
    assert db_session.query(Task).count() == 1
    db_session.refresh(task)
    assert task.status == TaskStatus.IN_PROGRESS


def test_pending_updates_rejected_after_import_is_undone(client, project, task, enabled, monkeypatch, db_session):
    plan = plan_for(task.id)
    plan["proposals"] = plan["proposals"][:1]
    fake_model(monkeypatch, plan)
    data = parse_with_assistant(client, project).json()
    imported = next(r for r in db_session.query(AgentReview).all() if r.status == "applied")
    assert client.post(route(project, {"id": imported.id}, "/undo")).status_code == 200
    review = data["review"]
    response = client.post(route(project, review, "/apply"), json={"proposal_ids": [review["proposals"][0]["id"]]})
    assert response.status_code == 409
    assert client.get(f"/api/v1/projects/{project['id']}/agent/reviews?view=pending").json() == []
    db_session.refresh(task)
    assert task.status == TaskStatus.IN_PROGRESS


def test_pending_updates_are_separate_from_completed_history(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    completed = create(client, project).json()
    assert client.post(route(project, completed, "/apply"), json={"proposal_ids": [1]}).status_code == 200
    pending_plan = plan_for(task.id)
    pending_plan["proposals"] = pending_plan["proposals"][:1]
    fake_model(monkeypatch, pending_plan)
    response = client.post(f"/api/v1/projects/{project['id']}/agent/reviews",
                           json={**INPUT, "transcript": "Another discussion. " + TRANSCRIPT})
    assert response.status_code == 201, response.text
    pending = response.json()
    base = f"/api/v1/projects/{project['id']}/agent/reviews"
    assert [r["id"] for r in client.get(base + "?view=pending").json()] == [pending["id"]]
    assert [r["id"] for r in client.get(base + "?view=history").json()] == [completed["id"]]
    row = db_session.get(AgentReview, pending["id"])
    row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert client.get(base + "?view=pending").json() == []
    assert client.post(route(project, completed, "/undo")).status_code == 200
    assert client.get(base + "?view=history").json()[0]["status"] == "undone"
    assert client.get(base + "?view=invalid").status_code == 422


def test_pending_list_keeps_stale_updates_visible_under_history(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    pending = create(client, project).json()
    original = db_session.get(AgentReview, pending["id"])
    for index in range(12):
        db_session.add(AgentReview(id=f"completed-{index}", project_id=project["id"], status="undone",
                                  expires_at=original.expires_at, input_json=original.input_json,
                                  plan_json=original.plan_json, baseline_hash=original.baseline_hash,
                                  created_at=datetime.utcnow() + timedelta(seconds=index + 1)))
    db_session.commit()
    base = f"/api/v1/projects/{project['id']}/agent/reviews"
    assert len(client.get(base + "?view=history").json()) == 10
    assert [r["id"] for r in client.get(base + "?view=pending").json()] == [pending["id"]]
    task.description = "Someone changed this task after the suggestion."
    db_session.commit()
    rows = client.get(base + "?view=pending").json()
    assert rows[0]["id"] == pending["id"]
    assert rows[0]["stale"] is True
    assert "changed" in rows[0]["stale_reason"]


@pytest.mark.parametrize("model,thinking", [("gemini-3.5-flash", {"thinkingLevel": "LOW"}), ("gemini-2.5-flash", None)])
def test_transport_leaves_room_for_complete_tool_output(monkeypatch, model, thinking):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured = {}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({"candidates": [{"finishReason": "STOP", "content": call("read_board")}]}).encode()
    def urlopen(request, timeout):
        captured.update(json.loads(request.data))
        return Response()
    monkeypatch.setattr(agent.urllib.request, "urlopen", urlopen)
    content = agent.model_turn([], ["read_board"], model, 90)
    assert content["parts"][0]["functionCall"]["name"] == "read_board"
    assert captured["generationConfig"]["maxOutputTokens"] >= 16384
    assert captured["generationConfig"].get("thinkingConfig") == thinking



def test_parse_schedules_summary_for_saved_meeting(client, project, task, enabled, monkeypatch):
    fake_model(monkeypatch, {"summary": "Discussion only.", "questions": [], "proposals": []})
    written = []
    monkeypatch.setattr(agent_api, "write_summary", written.append)
    response = parse_with_assistant(client, project)
    assert response.status_code == 201, response.text
    assert written == [response.json()["meeting_id"]]


def mutate_during_generation(monkeypatch, mutation):
    original = agent.model_turn
    mutated = False
    def turn(contents, allowed, model, timeout):
        nonlocal mutated
        if not mutated:  # the board snapshot is taken before the first model turn
            mutation()
            mutated = True
        return original(contents, allowed, model, timeout)
    monkeypatch.setattr(agent, "model_turn", turn)


def test_parse_preserves_import_when_unrelated_checklist_changes(client, project, task, enabled, monkeypatch, db_session):
    from app.models.models import Subtask
    other = Task(project_id=project["id"], description="Unrelated task")
    db_session.add(other)
    db_session.flush()
    child = Subtask(task_id=other.id, title="Independent work", done=False)
    db_session.add(child)
    db_session.commit()
    fake_model(monkeypatch, plan_for(task.id))
    def mutate():
        child.done = True
        db_session.commit()
    mutate_during_generation(monkeypatch, mutate)
    response = parse_with_assistant(client, project)
    assert response.status_code == 201, response.text
    assert response.json()["new_task_count"] == 1
    assert response.json()["review"]["proposals"][0]["before"]["status"] == "in_progress"
    assert db_session.query(Meeting).count() == 1
    assert db_session.get(Subtask, child.id).done
    assert db_session.query(AgentReview).filter_by(status="draft").count() == 1
    imported = db_session.query(AgentReview).filter_by(status="applied").one()
    assert all(p["kind"] == "create" for p in json.loads(imported.plan_json)["proposals"])


@pytest.mark.parametrize("change", ["owner", "delete"])
def test_parse_withholds_changed_target_but_saves_meeting_and_new_tasks(client, project, task, enabled, monkeypatch, db_session, change):
    fake_model(monkeypatch, plan_for(task.id))
    def mutate():
        if change == "delete": db_session.delete(task)
        else: task.owner = "New owner"
        db_session.commit()
    mutate_during_generation(monkeypatch, mutate)
    response = parse_with_assistant(client, project)
    assert response.status_code == 201, response.text
    assert response.json()["new_task_count"] == 1
    assert response.json()["review"] is None
    assert any("changed while parsing" in q for q in response.json()["questions"])
    assert db_session.query(Meeting).count() == 1
    assert db_session.query(AgentReview).filter_by(status="draft").count() == 0


def test_parse_suppresses_duplicate_added_during_model_call(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    def mutate():
        db_session.add(Task(project_id=project["id"], description="Write release notes"))
        db_session.commit()
    mutate_during_generation(monkeypatch, mutate)
    response = parse_with_assistant(client, project)
    assert response.status_code == 201, response.text
    assert response.json()["new_task_count"] == 0
    assert response.json()["questions"]
    assert db_session.query(Meeting).count() == 1
    assert db_session.query(Task).count() == 2


def test_updates_remain_actionable_after_unrelated_edits_and_undo_preserves_children(client, project, task, enabled, monkeypatch, db_session):
    from app.models.models import Subtask
    fake_model(monkeypatch, plan_for(task.id))
    review = create(client, project).json()
    other = Task(project_id=project["id"], description="Independent work")
    db_session.add(other)
    child = Subtask(task_id=task.id, title="Checklist content", done=False)
    db_session.add(child)
    db_session.commit()
    base = f"/api/v1/projects/{project['id']}/agent/reviews"
    assert client.get(base + "?view=pending").json()[0]["stale"] is False
    applied = client.post(route(project, review, "/apply"), json={"proposal_ids": [0]})
    assert applied.status_code == 200, applied.text
    child.done = True
    db_session.commit()
    assert client.post(route(project, review, "/undo")).status_code == 200
    assert db_session.get(Subtask, child.id).done
    assert db_session.get(Task, other.id) is not None


def test_selecting_unchanged_target_succeeds_even_if_unselected_target_changed(client, project, task, enabled, monkeypatch, db_session):
    other = Task(project_id=project["id"], description="Other work", status=TaskStatus.TODO)
    db_session.add(other)
    db_session.commit()
    plan = plan_for(task.id)
    plan["proposals"].append({"kind": "update", "task_id": other.id,
       "after": {"description": other.description, "owner": None, "deadline": None, "status": "done"},
       "evidence": "The landing page design is now finished and approved.", "reason": "Test only."})
    fake_model(monkeypatch, plan)
    review = create(client, project).json()
    other.owner = "Changed owner"
    db_session.commit()
    fetched = client.get(route(project, review)).json()
    assert fetched["stale"] is True
    other_id = next(p["id"] for p in fetched["proposals"] if p["task_id"] == other.id)
    assert fetched["unavailable_proposal_ids"] == [other_id]
    assert client.post(route(project, review, "/apply"), json={"proposal_ids": [0]}).status_code == 200
    assert db_session.get(Task, other.id).owner == "Changed owner"


@pytest.mark.parametrize("owner,evidence,valid", [
    ("Bob", "Alex: The landing page design is now finished and approved.", False),
    ("Sam", "Sam: I will write the release notes by 5 November 2026.", True),
    ("sam", "Sam: I will write the release notes by 5 November 2026.", True),
    ("Al", "Alex: The landing page design is now finished and approved.", False),
    # A first name is enough: meetings rarely use full names.
    ("Sam Lee", "Sam: I will write the release notes by 5 November 2026.", True),
    ("Alex Lee", "Sam: I will write the release notes by 5 November 2026.", False),
])
def test_owner_must_be_named_in_proposal_evidence(owner, evidence, valid):
    plan = {"summary": "Test", "proposals": [plan_for(1)["proposals"][1]], "questions": []}
    plan["proposals"][0]["after"]["owner"] = owner
    plan["proposals"][0]["evidence"] = evidence
    if valid:
        assert agent.validate_plan(plan, TRANSCRIPT, [], "2026-11-02")["proposals"]
    else:
        with pytest.raises(ValueError, match="owner"):
            agent.validate_plan(plan, TRANSCRIPT, [], "2026-11-02")


SPEAKER_TRANSCRIPT = """Meeting: Cutover review
Date: 2026-06-22

Aisha: Morning everyone.

Priya: I'm preparing the reconciliation. The GL side is done.
The sub-ledgers are still outstanding.

Aisha: Priya, can you send it Friday?

Priya: Friday, yes.

Ravi: Refunds are in, so payments are done. I'll add crash reporting next."""


@pytest.mark.parametrize("evidence,expected", [
    # Starts mid-turn: the turn's speaker is added.
    ("The GL side is done.", "Priya: The GL side is done."),
    # Starts on a continuation line of the same turn.
    ("The sub-ledgers are still outstanding.", "Priya: The sub-ledgers are still outstanding."),
    # Already labelled: unchanged.
    ("Aisha: Priya, can you send it Friday?", "Aisha: Priya, can you send it Friday?"),
    # A speaker with a single turn is still named, not skipped for an earlier speaker.
    ("I'll add crash reporting next.", "Ravi: I'll add crash reporting next."),
    # Inside a header line: no speaker is added.
    ("2026-06-22", "2026-06-22"),
    ("Cutover review", "Cutover review"),
])
def test_evidence_is_attributed_to_its_speaker(evidence, expected):
    assert agent.with_speaker(evidence, SPEAKER_TRANSCRIPT) == expected


def test_transcribed_speaker_numbers_are_attributed():
    # Recordings are transcribed as "Speaker N:" turns (app/llm/transcription.py).
    transcript = "Speaker 1: Can someone own the release notes?\n\nSpeaker 2: Sure. I'll write them by Friday."
    assert agent.with_speaker("I'll write them by Friday.", transcript) == "Speaker 2: I'll write them by Friday."


def test_speaker_is_added_only_when_requested():
    plan = {"summary": "Test", "proposals": [plan_for(1)["proposals"][1]], "questions": []}
    plan["proposals"][0]["after"]["owner"] = None
    plan["proposals"][0]["evidence"] = "The GL side is done."
    labelled = agent.validate_plan(copy.deepcopy(plan), SPEAKER_TRANSCRIPT, [], "2026-11-02", label_speakers=True)
    assert labelled["proposals"][0]["evidence"] == "Priya: The GL side is done."
    # Chat evidence quotes the user's own messages, which have no speakers.
    plain = agent.validate_plan(copy.deepcopy(plan), SPEAKER_TRANSCRIPT, [], "2026-11-02")
    assert plain["proposals"][0]["evidence"] == "The GL side is done."


def test_speaker_counts_as_naming_the_owner():
    plan = {"summary": "Test", "proposals": [plan_for(1)["proposals"][1]], "questions": []}
    plan["proposals"][0]["after"]["owner"] = "Ravi Kumar"
    plan["proposals"][0]["evidence"] = "I'll add crash reporting next."
    # "Ravi: I'll add crash reporting" is Ravi committing himself.
    assert agent.validate_plan(copy.deepcopy(plan), SPEAKER_TRANSCRIPT, [], "2026-11-02", label_speakers=True)["proposals"]
    # Without speaker labels (chat), the excerpt names nobody.
    with pytest.raises(ValueError, match="owner"):
        agent.validate_plan(copy.deepcopy(plan), SPEAKER_TRANSCRIPT, [], "2026-11-02")


def test_empty_owner_is_normalised_to_null():
    from app.schemas.agent import TaskFields
    fields = TaskFields(description="A task", owner="   ", deadline=None, status="todo")
    assert fields.owner is None


def test_near_duplicate_creates_become_questions_instead_of_tasks(client, project, task, enabled, monkeypatch, db_session):
    db_session.add(Task(project_id=project["id"], description="Write release notes"))
    db_session.commit()
    fake_model(monkeypatch, plan_for(task.id))
    response = parse_with_assistant(client, project)
    assert response.status_code == 201, response.text
    assert response.json()["new_task_count"] == 0
    assert any("already on the board" in q for q in response.json()["questions"])
    assert db_session.query(Task).count() == 2


def test_similar_but_distinct_tasks_are_not_lexically_blocked():
    for text in ["Write billing release notes", "Do not publish release notes"]:
        assert agent.likely_duplicate(text, [{"description": "Write release notes"}]) is None


def test_parse_failure_does_not_leave_committed_draft(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    from sqlalchemy import event
    def fail_pending(mapper, connection, target):
        if json.loads(target.plan_json).get("mode") == "meeting_updates":
            raise RuntimeError("Storage interrupted")
    event.listen(AgentReview, "before_insert", fail_pending)
    try:
        with pytest.raises(RuntimeError): parse_with_assistant(client, project)
    finally:
        event.remove(AgentReview, "before_insert", fail_pending)
        db_session.rollback()
    assert db_session.query(AgentReview).count() == 0
    assert db_session.query(Meeting).count() == 0


def test_duplicate_transcript_can_be_explicitly_added_again(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, {"summary": "Discussion", "proposals": [], "questions": []})
    first = parse_with_assistant(client, project)
    assert first.status_code == 201
    duplicate = parse_with_assistant(client, project)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "duplicate_transcript"
    added = client.post(f"/api/v1/projects/{project['id']}/agent/parse", json={**INPUT, "check_duplicate": False})
    assert added.status_code == 201, added.text
    assert db_session.query(Meeting).count() == 2


def test_malformed_tool_response_retries_within_budget(client, project, task, enabled, monkeypatch):
    original = fake_model(monkeypatch, plan_for(task.id))
    valid = agent.model_turn
    failed = False
    def turn(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise agent.RecoverableModelError("Return a valid tool call.")
        return valid(*args, **kwargs)
    monkeypatch.setattr(agent, "model_turn", turn)
    response = create(client, project)
    assert response.status_code == 201, response.text
    assert response.json()["steps"] == 2  # one rejected tool response, then the review
    assert original


@pytest.fixture
def agent_limits_on():
    from app.ratelimit import limiter
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


def test_review_and_both_parse_paths_share_configurable_parse_limit(client, project, task, enabled, monkeypatch, agent_limits_on):
    monkeypatch.setenv("RATE_LIMIT_PARSE", "1/hour")
    monkeypatch.setenv("RATE_LIMIT_AI", "1000/hour")
    fake_model(monkeypatch, plan_for(task.id))
    assert create(client, project).status_code == 201
    assert parse_with_assistant(client, project).status_code == 429
    response = client.post("/api/v1/transcripts", json={"project_id": project["id"], "transcript_text": "Another meeting"})
    assert response.status_code == 429


def test_agent_calls_reserve_shared_ai_budget_with_summary(client, project, task, enabled, monkeypatch, db_session, agent_limits_on):
    monkeypatch.setenv("RATE_LIMIT_AI", "9/hour")
    monkeypatch.setenv("RATE_LIMIT_PARSE", "100/hour")
    fake_model(monkeypatch, plan_for(task.id))
    assert create(client, project).status_code == 201  # reserves the parser call and six model calls
    meeting = Meeting(project_id=project["id"], title="Planning", transcript_text="Discussed work.", status=MeetingStatus.COMPLETE)
    db_session.add(meeting)
    db_session.commit()
    assert client.post(f"/api/v1/transcripts/{meeting.id}/summary").status_code == 200
    assert client.post(f"/api/v1/transcripts/{meeting.id}/summary").status_code == 200
    assert client.post(f"/api/v1/transcripts/{meeting.id}/summary").status_code == 429


def test_chat_limit_can_be_configured(client, project, enabled, monkeypatch, agent_limits_on):
    monkeypatch.setenv("RATE_LIMIT_AGENT_CHAT", "1/hour")
    monkeypatch.setenv("RATE_LIMIT_AI", "1000/hour")
    monkeypatch.setattr(agent_api.assistant_llm, "run_chat", lambda *a: {
        "answer": "Hello", "sources": [], "proposals": [], "questions": [], "next_action": "none"})
    path = f"/api/v1/projects/{project['id']}/agent/chat"
    body = {"message": "Hello", "current_date": "2026-11-02"}
    assert client.post(path, json=body).status_code == 200
    assert client.post(path, json=body).status_code == 429


@pytest.mark.parametrize("reason,recoverable", [("MALFORMED_FUNCTION_CALL", True), ("UNEXPECTED_TOOL_CALL", True), ("SAFETY", False)])
def test_provider_finish_reason_is_recoverable_only_for_malformed_tools(monkeypatch, enabled, reason, recoverable):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({"candidates": [{"finishReason": reason, "content": {"parts": [{"text": "PRIVATE PROVIDER OUTPUT"}]}}]}).encode()
    monkeypatch.setattr(agent.urllib.request, "urlopen", lambda *a, **k: Response())
    with pytest.raises(agent.gemini.GeminiError) as caught:
        agent.model_turn([], ["read_board"], "existing-flash-model", 90)
    assert isinstance(caught.value, agent.RecoverableModelError) is recoverable
    assert "PRIVATE PROVIDER OUTPUT" not in str(caught.value)


def test_meeting_suggestions_remain_available_the_next_day(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    data = parse_with_assistant(client, project).json()
    review = data["review"]
    row = db_session.get(AgentReview, review["id"])
    row.expires_at = datetime.utcnow() - timedelta(days=2)
    db_session.commit()
    path = f"/api/v1/projects/{project['id']}/agent/reviews"
    assert client.get(path + "?view=pending").json()[0]["id"] == review["id"]
    assert client.get(route(project, review)).json()["expires_at"] is None
    applied = client.post(route(project, review, "/apply"), json={"proposal_ids": [review["proposals"][0]["id"]]})
    assert applied.status_code == 200, applied.text
    assert db_session.get(Task, task.id).status == TaskStatus.DONE


def test_refresh_meeting_suggestions_rechecks_current_tasks_without_importing_more_work(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    data = parse_with_assistant(client, project).json()
    review = data["review"]
    task.deadline = date(2026, 11, 8)
    db_session.commit()
    assert client.get(route(project, review)).json()["stale"] is True
    fresh = plan_for(task.id)
    fresh["proposals"][0]["after"]["deadline"] = "2026-11-08"
    fresh["proposals"][1]["after"]["description"] = "Another new task that refresh must not import"
    fake_model(monkeypatch, fresh)
    response = client.post(route(project, review, "/refresh"))
    assert response.status_code == 200, response.text
    refreshed = response.json()
    assert refreshed["id"] == review["id"]
    assert refreshed["mode"] == "meeting_updates"
    assert refreshed["stale"] is False
    assert refreshed["expires_at"] is None
    assert len(refreshed["proposals"]) == 1
    assert refreshed["proposals"][0]["before"]["deadline"] == "2026-11-08"
    assert db_session.query(Meeting).count() == 1
    assert db_session.query(Task).count() == 2
    assert db_session.query(AgentReview).count() == 2
    assert client.post(route(project, review, "/apply"), json={"proposal_ids": [refreshed["proposals"][0]["id"]]}).status_code == 200


def test_refresh_rechecks_permissions_and_resolved_state(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    review = parse_with_assistant(client, project).json()["review"]
    client.headers["X-Workspace-Token"] = project["view_token"]
    assert client.post(route(project, review, "/refresh")).status_code == 403
    client.headers["X-Workspace-Token"] = project["edit_token"]
    assert client.post(route(project, review, "/apply"), json={"proposal_ids": [0]}).status_code == 200
    assert client.post(route(project, review, "/refresh")).status_code == 409


def test_refresh_cannot_resurrect_a_meeting_that_was_removed(client, project, task, enabled, monkeypatch, db_session):
    fake_model(monkeypatch, plan_for(task.id))
    review = parse_with_assistant(client, project).json()["review"]
    imported = db_session.query(AgentReview).filter_by(status="applied").one()
    assert client.post(route(project, {"id": imported.id}, "/undo")).status_code == 200
    monkeypatch.setattr(agent, "model_turn", lambda *a, **k: pytest.fail("Removed source must not reach model"))
    assert client.post(route(project, review, "/refresh")).status_code == 409
    assert db_session.query(Meeting).count() == 0


def upload_recording(client, project):
    return client.post(f"/api/v1/projects/{project['id']}/agent/recordings",
                       data={"title": INPUT["title"], "meeting_date": INPUT["meeting_date"]},
                       files={"file": ("follow-up.wav", b"recorded audio", "audio/wav")})


@pytest.fixture
def recording(monkeypatch):
    from pathlib import Path
    from app.api import transcripts

    paths = []
    def transcribe(path):
        assert Path(path).read_bytes() == b"recorded audio"
        paths.append(Path(path))
        return TRANSCRIPT
    monkeypatch.setattr(transcripts.transcription, "is_available", lambda: True)
    monkeypatch.setattr(transcripts.transcription, "transcribe_file", transcribe)
    monkeypatch.setattr(transcripts.TranscriptParser, "parse",
                        lambda *a, **k: pytest.fail("Assistant recordings must not use the old parser"))
    return paths


def test_recording_saves_new_tasks_and_withholds_updates(client, project, task, enabled, recording, monkeypatch, db_session):
    plan = plan_for(task.id)
    plan["questions"] = ["Who will review the release notes?"]
    fake_model(monkeypatch, plan)
    response = upload_recording(client, project)
    assert response.status_code == 201, response.text
    meeting_id = response.json()["id"]
    meeting = db_session.get(Meeting, meeting_id)
    assert meeting.status == MeetingStatus.COMPLETE
    assert meeting.transcript_text == TRANSCRIPT
    assert db_session.query(Meeting).count() == 1  # Reuse the processing recording row.
    assert db_session.query(Task).count() == 2
    assert db_session.get(Task, task.id).status == TaskStatus.IN_PROGRESS
    assert db_session.query(Task).filter_by(meeting_id=meeting_id).one().description == "Write the release notes"
    assert recording and all(not p.exists() for p in recording)

    path = f"/api/v1/projects/{project['id']}/agent/recordings/{meeting_id}/result"
    result = client.get(path)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["new_task_count"] == 1
    assert data["saved_review"]["receipt"]["meeting_id"] == meeting_id
    assert data["questions"] == plan["questions"]
    review = data["review"]
    assert review["mode"] == "meeting_updates"
    assert review["expires_at"] is None
    assert [p["kind"] for p in review["proposals"]] == ["update"]
    assert len(client.get(f"/api/v1/projects/{project['id']}/agent/reviews?view=pending").json()) == 1
    assert client.post(route(project, review, "/apply"), json={"proposal_ids": [0]}).status_code == 200
    assert db_session.get(Task, task.id).status == TaskStatus.DONE
    assert client.post(route(project, review, "/undo")).status_code == 200
    assert db_session.get(Task, task.id).status == TaskStatus.IN_PROGRESS
    assert db_session.get(Meeting, meeting_id) is not None
    assert db_session.query(Task).count() == 2
    assert client.get(path).json()["review"] is None

    client.headers["X-Workspace-Token"] = project["view_token"]
    assert client.get(path).status_code == 403
    assert upload_recording(client, project).status_code == 403


def test_recording_without_updates_returns_clarifications(client, project, task, enabled, recording, monkeypatch, db_session):
    plan = plan_for(task.id)
    plan["proposals"] = []
    plan["questions"] = ["Who owns the next step?"]
    monkeypatch.setattr(agent_api, "extract_candidates", lambda payload: [])
    fake_model(monkeypatch, plan)
    response = upload_recording(client, project)
    assert response.status_code == 201, response.text
    meeting_id = response.json()["id"]
    result = client.get(f"/api/v1/projects/{project['id']}/agent/recordings/{meeting_id}/result").json()
    assert result["review"] is None
    assert result["new_task_count"] == 0
    assert result["questions"] == plan["questions"]
    assert db_session.get(Meeting, meeting_id).status == MeetingStatus.COMPLETE
    assert db_session.query(Task).count() == 1


def test_recording_assistant_failure_does_not_fall_back_or_save_tasks(client, project, task, enabled, recording, monkeypatch, db_session):
    def fail(*a, **k):
        raise agent.GeminiError("Model unavailable")
    monkeypatch.setattr(agent, "run_review", fail)
    response = upload_recording(client, project)
    assert response.status_code == 201, response.text
    meeting = db_session.get(Meeting, response.json()["id"])
    assert meeting.status == MeetingStatus.FAILED
    assert meeting.transcript_text == TRANSCRIPT
    assert meeting.error_message
    assert db_session.query(Task).count() == 1
    assert db_session.query(AgentReview).count() == 0
    assert recording and all(not p.exists() for p in recording)


def test_recording_import_rolls_back_if_pending_review_cannot_save(client, project, task, enabled, recording, monkeypatch, db_session):
    from sqlalchemy import event
    fake_model(monkeypatch, plan_for(task.id))
    def fail_pending(_mapper, _connection, target):
        if json.loads(target.plan_json).get("mode") == "meeting_updates":
            raise RuntimeError("Database write failed")
    event.listen(AgentReview, "before_insert", fail_pending)
    try:
        response = upload_recording(client, project)
    finally:
        event.remove(AgentReview, "before_insert", fail_pending)
    assert response.status_code == 201, response.text
    assert db_session.get(Meeting, response.json()["id"]).status == MeetingStatus.FAILED
    assert db_session.query(Task).count() == 1
    assert db_session.get(Task, task.id).status == TaskStatus.IN_PROGRESS
    assert db_session.query(AgentReview).count() == 0
    assert all(not p.exists() for p in recording)


def test_recording_deleted_during_review_leaves_no_tasks_or_reviews(client, project, task, enabled, recording, monkeypatch, db_session):
    from app.models.models import Project
    run_review = agent.run_review
    fake_model(monkeypatch, plan_for(task.id))
    def delete_while_reviewing(*a, **k):
        plan = run_review(*a, **k)
        db_session.delete(db_session.get(Project, project["id"]))
        db_session.commit()
        return plan
    monkeypatch.setattr(agent, "run_review", delete_while_reviewing)
    response = upload_recording(client, project)
    assert response.status_code == 201, response.text
    assert db_session.query(Meeting).count() == 0
    assert db_session.query(Task).count() == 0
    assert db_session.query(AgentReview).count() == 0
    assert recording and all(not p.exists() for p in recording)


def test_assistant_recording_rejects_disabled_feature_and_missing_key_before_upload(client, project, enabled, recording, monkeypatch, db_session):
    monkeypatch.setenv("ENABLE_MEETING_AGENT", "false")
    assert upload_recording(client, project).status_code == 404
    monkeypatch.setenv("ENABLE_MEETING_AGENT", "true")
    monkeypatch.delenv("GEMINI_API_KEY")
    assert upload_recording(client, project).status_code == 503
    assert recording == []
    assert db_session.query(Meeting).count() == 0


def test_recording_reserves_shared_ai_budget_including_summary(client, project, task, enabled, recording, monkeypatch, db_session, agent_limits_on):
    monkeypatch.setenv("RATE_LIMIT_AI", "8/hour")
    fake_model(monkeypatch, plan_for(task.id))
    assert upload_recording(client, project).status_code == 201
    assert create(client, project).status_code == 429
    assert upload_recording(client, project).status_code == 429
    assert len(recording) == 1
    assert db_session.query(Meeting).count() == 1


def test_recordings_share_parse_allowance_with_text(client, project, task, enabled, recording, monkeypatch, db_session, agent_limits_on):
    monkeypatch.setenv("RATE_LIMIT_PARSE", "1/hour")
    fake_model(monkeypatch, plan_for(task.id))
    assert create(client, project).status_code == 201
    assert upload_recording(client, project).status_code == 429
    assert recording == []
    assert db_session.query(Meeting).count() == 0


def test_empty_board_uses_the_parser_alone(client, project, enabled, monkeypatch, db_session):
    calls = fake_model(monkeypatch, plan_for(1))
    response = parse_with_assistant(client, project)
    assert response.status_code == 201, response.text
    assert calls == []  # nothing to reconcile, so the assistant is not called
    assert response.json()["new_task_count"] == 1
    created = db_session.query(Task).one()
    assert (created.description, created.owner, created.confidence) == ("Write the release notes", "Sam", 0.9)
    assert created.source_decision == "Sam committed to the release notes."


def test_parser_tasks_keep_their_score_and_source_on_a_board_with_tasks(client, project, task, enabled, monkeypatch, db_session):
    calls = fake_model(monkeypatch, plan_for(task.id))
    assert parse_with_assistant(client, project).status_code == 201
    # The assistant was shown the parser's candidates to reconcile.
    request = json.loads(calls[0][0]["parts"][0]["text"])
    assert request["candidate_tasks"][0]["description"] == "Write the release notes"
    created = db_session.query(Task).filter(Task.id != task.id).one()
    assert created.confidence == 0.9
    assert created.source_decision == "Sam committed to the release notes."


def test_assistant_creates_are_ignored_when_candidates_are_given():
    plan = {"summary": "Test", "questions": [], "proposals": [plan_for(1)["proposals"][1]]}
    validated = agent.validate_plan(plan, TRANSCRIPT, [], "2026-11-02", candidates=CANDIDATES)
    assert validated["proposals"] == []


@pytest.mark.parametrize("existing,match", [
    ([{"item": 1, "task_id": 7}], "candidate_tasks index"),
    ([{"item": 0, "task_id": 7}, {"item": 0, "task_id": 7}], "candidate_tasks index"),
    ([{"item": 0, "task_id": 99}], "tasks on this board"),
])
def test_existing_items_must_name_real_candidates_and_tasks(existing, match):
    board = [{"id": 7, "description": "Write release notes", "owner": "Sam", "deadline": None,
              "status": "todo", "meeting_date": None}]
    plan = {"summary": "Test", "questions": [], "proposals": [], "existing_items": existing}
    with pytest.raises(ValueError, match=match):
        agent.validate_plan(plan, TRANSCRIPT, board, "2026-11-02", candidates=CANDIDATES)


def test_parser_failure_saves_nothing(client, project, task, enabled, monkeypatch, db_session):
    def fail(self, transcript, meeting_date=None):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(agent_api.TranscriptParser, "parse", fail)
    monkeypatch.setattr(agent_api, "extract_candidates", REAL_EXTRACT_CANDIDATES)  # undo the fixture's fake
    response = parse_with_assistant(client, project)
    assert response.status_code == 502
    assert db_session.query(Meeting).count() == 0
    assert db_session.query(Task).count() == 1


def import_with_match(client, project, task, monkeypatch, updates=False):
    """Import TRANSCRIPT with the parser's one candidate matched to `task` (and, optionally, an update)."""
    plan = plan_for(task.id)
    plan["proposals"] = plan["proposals"][:1] if updates else []
    plan["existing_items"] = [{"item": 0, "task_id": task.id}]
    fake_model(monkeypatch, plan)
    response = parse_with_assistant(client, project)
    assert response.status_code == 201, response.text
    return response.json()


def test_matched_candidate_waits_as_an_unticked_possible_duplicate(client, project, task, enabled, monkeypatch, db_session):
    data = import_with_match(client, project, task, monkeypatch)
    assert data["new_task_count"] == 0
    assert any("already on the board" in q and "Changes" in q for q in data["questions"])
    item = data["review"]["proposals"][0]
    assert item["possible_duplicate"] and item["duplicate_of"]["description"] == "Finish the landing page design"
    assert item["id"] not in data["review"]["unavailable_proposal_ids"]  # resembling a task is expected here
    # It does not count as a suggested change in the toolbar badge.
    pending = client.get(f"/api/v1/projects/{project['id']}/agent/reviews?view=pending").json()
    assert [(p["change_count"], p["possible_duplicates"]) for p in pending] == [(0, 1)]


def test_adding_a_possible_duplicate_links_it_to_its_meeting_and_undo_keeps_the_meeting(
        client, project, task, enabled, monkeypatch, db_session):
    data = import_with_match(client, project, task, monkeypatch)
    review, item = data["review"], data["review"]["proposals"][0]
    applied = client.post(route(project, review, "/apply"), json={"proposal_ids": [item["id"]]})
    assert applied.status_code == 200, applied.text
    added = db_session.query(Task).filter(Task.id != task.id).one()
    assert (added.description, added.meeting_id, added.confidence) == ("Write the release notes", data["meeting_id"], 0.9)
    assert client.post(route(project, review, "/undo")).status_code == 200
    assert db_session.query(Task).count() == 1
    assert db_session.query(Meeting).count() == 1  # only the added task is removed


def test_refresh_keeps_possible_duplicates(client, project, task, enabled, monkeypatch, db_session):
    review = import_with_match(client, project, task, monkeypatch, updates=True)["review"]
    fake_model(monkeypatch, plan_for(task.id))
    refreshed = client.post(route(project, review, "/refresh"))
    assert refreshed.status_code == 200, refreshed.text
    kinds = sorted((p["kind"], bool(p.get("possible_duplicate"))) for p in refreshed.json()["proposals"])
    assert kinds == [("create", True), ("update", False)]
    assert len({p["id"] for p in refreshed.json()["proposals"]}) == 2


def test_dismissing_resolves_a_draft_without_changing_the_board(client, project, task, enabled, monkeypatch, db_session):
    review = import_with_match(client, project, task, monkeypatch, updates=True)["review"]
    dismissed = client.post(route(project, review, "/dismiss"))
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"
    db_session.refresh(task)
    assert task.status == TaskStatus.IN_PROGRESS and db_session.query(Task).count() == 1
    assert client.get(f"/api/v1/projects/{project['id']}/agent/reviews?view=pending").json() == []
    history = client.get(f"/api/v1/projects/{project['id']}/agent/reviews?view=history").json()
    assert [h["status"] for h in history if h["id"] == review["id"]] == ["dismissed"]
    assert client.post(route(project, review, "/dismiss")).status_code == 200  # repeating is harmless
    assert client.post(route(project, review, "/apply"), json={"proposal_ids": [0]}).status_code == 409



def test_empty_board_import_reserves_only_the_parser_and_summary(client, project, enabled, monkeypatch, agent_limits_on):
    monkeypatch.setenv("RATE_LIMIT_AI", "3/hour")
    monkeypatch.setenv("RATE_LIMIT_PARSE", "100/hour")
    fake_model(monkeypatch, plan_for(1))
    # Empty board: the assistant is not called, so 2 of the 3 calls are reserved.
    assert parse_with_assistant(client, project).status_code == 201
    # The board now has a task, so a review reserves the parser call and the assistant's six.
    assert client.post(f"/api/v1/projects/{project['id']}/agent/reviews",
                       json={**INPUT, "transcript": INPUT["transcript"] + " Second meeting."}).status_code == 429


def test_meeting_review_keeps_an_existing_deadline_and_owner():
    board = [{"id": 1, "description": "Finish the landing page design", "owner": "Alex",
              "deadline": "2026-11-04", "status": "in_progress", "meeting_date": None}]
    plan = plan_for(1)
    plan["proposals"] = plan["proposals"][:1]
    plan["proposals"][0]["after"].update(deadline=None, status="done")
    kept = agent.validate_plan(copy.deepcopy(plan), TRANSCRIPT, board, "2026-11-02", keep_set_fields=True)
    assert kept["proposals"][0]["after"] == {**plan["proposals"][0]["after"], "deadline": "2026-11-04"}
    # Clearing alone leaves nothing to suggest, so the proposal is dropped rather than rejected.
    only_clear = copy.deepcopy(plan)
    only_clear["proposals"][0]["after"].update(status="in_progress", owner=None)
    assert agent.validate_plan(only_clear, TRANSCRIPT, board, "2026-11-02", keep_set_fields=True)["proposals"] == []
    # Chat, where a user can ask for a deadline to be removed, may still clear it.
    assert agent.validate_plan(copy.deepcopy(plan), TRANSCRIPT, board, "2026-11-02")["proposals"][0]["after"]["deadline"] is None
