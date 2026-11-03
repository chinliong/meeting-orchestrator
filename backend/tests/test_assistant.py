"""Project chat uses fresh scoped context; proposed changes remain explicitly approved."""
import copy
import json
from datetime import date

import pytest

from app.llm import agent, assistant
from app.models.models import AgentReview, Meeting, MeetingStatus, Task, TaskStatus
from app.schemas.agent import ChatInput


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    monkeypatch.setenv("ENABLE_MEETING_AGENT", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "existing-flash-model")


@pytest.fixture
def audit(db_session, project):
    task = Task(project_id=project["id"], description="Complete accessibility audit", owner="Priya",
                deadline=date(2026, 11, 3), status=TaskStatus.IN_PROGRESS)
    db_session.add(task)
    db_session.commit()
    return task


def tool(name, args=None):
    return {"role": "model", "parts": [{"functionCall": {"name": name, "args": args or {}, "id": "call-1"},
                                          "thoughtSignature": "keep-me"}]}


def reply(**kwargs):
    return {"answer": "Here is what I found.", "references": [], "proposals": [], "questions": [],
            "next_action": "none", **kwargs}


def simulate(monkeypatch, answer, additional=None):
    calls = []
    remaining = list(additional or [])
    def turn(contents, allowed, model, timeout, **kwargs):
        assert model == "existing-flash-model"
        assert kwargs["system_prompt"] == assistant.SYSTEM
        assert kwargs["tools"] == assistant.TOOLS
        calls.append(copy.deepcopy(contents))
        if allowed == ["read_board"]:
            return tool("read_board")
        if remaining:
            return remaining.pop(0)
        return tool("finish_chat", answer)
    monkeypatch.setattr(agent, "model_turn", turn)
    return calls


def chat(client, project, message="What is Priya working on?", **kwargs):
    return client.post(f"/api/v1/projects/{project['id']}/agent/chat", json={
        "message": message, "current_date": "2026-11-02", **kwargs})


def proposal(task_id=None):
    return {"kind": "update" if task_id else "create", "task_id": task_id,
            "after": {"description": "Complete accessibility audit" if task_id else "Write release notes",
                      "owner": "Priya", "deadline": "2026-11-06", "status": "in_progress" if task_id else "todo"},
            "reason": "Propose the requested change.", "evidence": "Move the audit deadline to Friday."}


def test_answer_has_verified_task_source_and_does_not_write(client, project, audit, monkeypatch, db_session):
    calls = simulate(monkeypatch, reply(answer="Priya is working on the accessibility audit.", references=[
        {"kind": "task", "id": audit.id, "quote": audit.description}]), additional=[
        tool("query_tasks", {"owner": "Priya", "status": "open", "due": "any"})])
    response = chat(client, project)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["review"] is None
    assert data["sources"][0]["title"] == audit.description
    assert data["sources"][0]["deadline"] == "2026-11-03"
    assert db_session.query(AgentReview).count() == 0
    assert db_session.query(Task).count() == 1
    assert calls[1][1]["parts"][0]["thoughtSignature"] == "keep-me"
    assert calls[1][2]["parts"][0]["functionResponse"]["id"] == "call-1"
    assert calls[2][-1]["parts"][0]["functionResponse"]["response"]["total"] == 1


def test_chat_proposal_applies_and_undoes_without_creating_meeting(client, project, audit, monkeypatch, db_session):
    simulate(monkeypatch, reply(proposals=[proposal(audit.id)]))
    response = chat(client, project, "Move the audit deadline to Friday.")
    assert response.status_code == 200, response.text
    review = response.json()["review"]
    assert review["mode"] == "chat"
    assert audit.deadline == date(2026, 11, 3)
    path = f"/api/v1/projects/{project['id']}/agent/reviews/{review['id']}"
    applied = client.post(path + "/apply", json={"proposal_ids": [0]})
    assert applied.status_code == 200, applied.text
    assert applied.json()["receipt"]["meeting_id"] is None
    db_session.refresh(audit)
    assert audit.deadline == date(2026, 11, 6)
    assert db_session.query(Meeting).count() == 0
    assert client.post(path + "/apply", json={"proposal_ids": [0]}).status_code == 200
    assert client.post(path + "/undo").status_code == 200
    db_session.refresh(audit)
    assert audit.deadline == date(2026, 11, 3)


def test_new_task_from_chat_is_manual_and_reversible(client, project, monkeypatch, db_session):
    new = proposal()
    new["evidence"] = "Create a release notes task for Priya due Friday."
    simulate(monkeypatch, reply(proposals=[new]))
    response = chat(client, project, new["evidence"])
    assert response.status_code == 200, response.text
    review = response.json()["review"]
    path = f"/api/v1/projects/{project['id']}/agent/reviews/{review['id']}"
    assert client.post(path + "/apply", json={"proposal_ids": [0]}).status_code == 200
    task = db_session.query(Task).one()
    assert task.meeting_id is None
    assert db_session.query(Meeting).count() == 0
    assert client.post(path + "/undo").status_code == 200
    assert db_session.query(Task).count() == 0


def test_viewer_can_ask_but_cannot_receive_write_proposals(client, project, audit, monkeypatch):
    client.headers["X-Workspace-Token"] = project["view_token"]
    calls = simulate(monkeypatch, reply(answer="You have view-only access."))
    assert chat(client, project).status_code == 200
    assert json.loads(calls[0][0]["parts"][0]["text"])["can_edit"] is False
    simulate(monkeypatch, reply(proposals=[proposal(audit.id)]))
    assert chat(client, project, "Move the audit deadline to Friday.").status_code == 502


def test_unauthorised_board_does_not_reach_model(client, project, monkeypatch):
    client.headers["X-Workspace-Token"] = "wrong-token"
    monkeypatch.setattr(agent, "model_turn", lambda *a, **k: pytest.fail("Model must not be called"))
    assert chat(client, project).status_code == 403


@pytest.mark.parametrize("invalid", ["foreign_task", "invented_quote", "unread_meeting", "assistant_evidence"])
def test_invalid_sources_and_authority_are_rejected(client, project, audit, monkeypatch, db_session, invalid):
    answer = reply()
    if invalid == "foreign_task":
        answer["references"] = [{"kind": "task", "id": 9999, "quote": audit.description}]
    elif invalid == "invented_quote":
        answer["references"] = [{"kind": "task", "id": audit.id, "quote": "A fabricated source"}]
    elif invalid == "unread_meeting":
        meeting = Meeting(project_id=project["id"], title="Planning", transcript_text="We agreed a deadline.",
                          meeting_date=date(2026, 11, 1), status=MeetingStatus.COMPLETE)
        db_session.add(meeting)
        db_session.commit()
        answer["references"] = [{"kind": "meeting", "id": meeting.id, "quote": "We agreed a deadline."}]
    else:
        answer["proposals"] = [proposal(audit.id)]
    calls = simulate(monkeypatch, answer)
    response = chat(client, project, history=[{"role": "assistant", "content": "Move the audit deadline to Friday."}])
    assert response.status_code == 502
    assert len(calls) == agent.MAX_STEPS
    assert db_session.query(AgentReview).count() == 0


def test_meeting_answer_reads_transcript_and_returns_exact_quote(client, project, audit, db_session, monkeypatch):
    meeting = Meeting(project_id=project["id"], title="Launch planning", transcript_text="We agreed to launch on Monday.",
                      meeting_date=date(2026, 11, 1), status=MeetingStatus.COMPLETE)
    db_session.add(meeting)
    db_session.commit()
    simulate(monkeypatch, reply(references=[{"kind": "meeting", "id": meeting.id,
                                           "quote": "We agreed to launch on Monday."}]),
             [tool("read_meeting", {"meeting_id": meeting.id})])
    response = chat(client, project, "What did we decide about launch?")
    assert response.status_code == 200
    assert response.json()["sources"][0]["title"] == "Launch planning"


def test_follow_up_can_use_user_history_but_context_is_fresh(client, project, audit, monkeypatch, db_session):
    change = proposal(audit.id)
    calls = simulate(monkeypatch, reply(proposals=[change]))
    audit.deadline = date(2026, 11, 4)
    db_session.commit()
    response = chat(client, project, "Yes, the accessibility audit.", history=[
        {"role": "user", "content": "Move the audit deadline to Friday."},
        {"role": "assistant", "content": "Which audit?"}])
    assert response.status_code == 200, response.text
    assert response.json()["review"]["proposals"][0]["before"]["deadline"] == "2026-11-04"
    assert "conversation" in json.loads(calls[0][0]["parts"][0]["text"])


def test_chat_proposal_rechecks_staleness(client, project, audit, monkeypatch, db_session):
    simulate(monkeypatch, reply(proposals=[proposal(audit.id)]))
    review = chat(client, project, "Move the audit deadline to Friday.").json()["review"]
    audit.owner = "Alex"
    db_session.commit()
    result = client.post(f"/api/v1/projects/{project['id']}/agent/reviews/{review['id']}/apply", json={"proposal_ids": [0]})
    assert result.status_code == 409


def test_transcript_request_routes_to_meeting_review_without_writes(client, project, monkeypatch, db_session):
    simulate(monkeypatch, reply(answer="Open the meeting review to set its date.", next_action="review_meeting"))
    response = chat(client, project, "Compare my new meeting transcript with the board.")
    assert response.status_code == 200
    assert response.json()["next_action"] == "review_meeting"
    assert response.json()["review"] is None
    assert db_session.query(Meeting).count() == 0


def test_scope_never_contains_other_project_data(client, project, audit, monkeypatch, db_session):
    other = client.post("/api/v1/projects", json={"name": "Secret project"}).json()
    db_session.add(Task(project_id=other["id"], description="PRIVATE TASK", status=TaskStatus.TODO))
    db_session.commit()
    calls = simulate(monkeypatch, reply())
    assert chat(client, project).status_code == 200
    assert "PRIVATE TASK" not in json.dumps(calls)
    assert "Secret project" not in json.dumps(calls)


def test_budget_failure_and_disabled_feature(client, project, monkeypatch):
    monkeypatch.setenv("ENABLE_MEETING_AGENT", "false")
    assert chat(client, project).status_code == 404
    monkeypatch.setenv("ENABLE_MEETING_AGENT", "true")
    monkeypatch.setattr(agent, "MAX_CONTEXT_CHARS", 1)
    assert chat(client, project).status_code == 422


def test_task_filter_dates_completed_work_and_exact_owner():
    tasks = [
        {"id": 1, "owner": "Priya", "status": "in_progress", "deadline": "2026-11-01"},
        {"id": 2, "owner": "Priya", "status": "done", "deadline": "2026-10-31"},
        {"id": 3, "owner": "Priya", "status": "todo", "deadline": "2026-11-02"},
        {"id": 4, "owner": "Priyanka", "status": "todo", "deadline": "2026-11-01"},
        {"id": 5, "owner": None, "status": "todo", "deadline": None},
        {"id": 6, "owner": "Priya", "status": "todo", "deadline": "2026-11-09"},
    ]
    today = date(2026, 11, 2)
    def query(owner="", status="any", due="any"):
        return assistant.query_tasks({"owner": owner, "status": status, "due": due}, tasks, today)
    assert [t["id"] for t in query(owner="priya", due="overdue")["tasks"]] == [1]
    assert query(due="overdue")["total"] == 2
    assert query(due="today")["total"] == 1
    assert query(due="next_7_days")["total"] == 1
    assert query(due="no_deadline")["total"] == 1
    assert query(status="open")["total"] == 5
    with pytest.raises(ValueError):
        query(status="blocked")


def test_arbitrary_tools_cannot_execute(monkeypatch):
    turns = iter([tool("read_board"), tool("send_email", {"to": "external@example.com"}), tool("finish_chat", reply())])
    captures = []
    def turn(contents, *args, **kwargs):
        captures.append(copy.deepcopy(contents))
        return next(turns)
    monkeypatch.setattr(agent, "model_turn", turn)
    assistant.run_chat(ChatInput(message="What can you do?", current_date="2026-11-02"), {"tasks": []}, {}, True)
    assert "not available at this step" in json.dumps(captures[-1])


def test_chat_cannot_save_empty_selection(client, project, audit, monkeypatch, db_session):
    simulate(monkeypatch, reply(proposals=[proposal(audit.id)]))
    review = chat(client, project, "Move the audit deadline to Friday.").json()["review"]
    response = client.post(f"/api/v1/projects/{project['id']}/agent/reviews/{review['id']}/apply", json={"proposal_ids": []})
    assert response.status_code == 422
    assert db_session.get(AgentReview, review["id"]).status == "draft"
    assert db_session.query(Meeting).count() == 0


def test_consumed_chat_request_cannot_authorize_a_later_edit(client, project, audit, monkeypatch, db_session):
    simulate(monkeypatch, reply(proposals=[proposal(audit.id)]))
    first = chat(client, project, "Move the audit deadline to Friday.").json()["review"]
    path = f"/api/v1/projects/{project['id']}/agent/reviews/{first['id']}"
    assert client.post(path + "/apply", json={"proposal_ids": [0]}).status_code == 200
    # Later manual work must not be overwritten just because an old request is in history.
    audit.deadline = date(2026, 11, 10)
    db_session.commit()
    response = chat(client, project, "What is due next week?", history=[
        {"role": "user", "content": "Move the audit deadline to Friday."},
        {"role": "assistant", "content": "That change was applied."}])
    assert response.status_code == 502
    assert db_session.query(AgentReview).count() == 1
    assert db_session.get(Task, audit.id).deadline == date(2026, 11, 10)
    # Explicitly asking again in the CURRENT message is a fresh authorization.
    again = chat(client, project, "Move the audit deadline to Friday.")
    assert again.status_code == 200, again.text
    assert db_session.query(AgentReview).count() == 2


def test_chat_retries_malformed_tool_response(monkeypatch):
    turns = iter([agent.RecoverableModelError("Return a valid tool call."), tool("read_board"), tool("finish_chat", reply())])
    def turn(*args, **kwargs):
        value = next(turns)
        if isinstance(value, Exception): raise value
        return value
    monkeypatch.setattr(agent, "model_turn", turn)
    result = assistant.run_chat(ChatInput(message="Hello", current_date="2026-11-02"), {"tasks": []}, {}, True)
    assert result["steps"] == 3


def test_refresh_chat_renews_request_without_applying_it(client, project, audit, monkeypatch, db_session):
    simulate(monkeypatch, reply(proposals=[proposal(audit.id)]))
    review = chat(client, project, "Move the audit deadline to Friday.").json()["review"]
    row = db_session.get(AgentReview, review["id"])
    from datetime import datetime, timedelta
    row.expires_at = datetime.utcnow() - timedelta(days=1)
    audit.deadline = date(2026, 11, 10)
    db_session.commit()
    response = client.post(f"/api/v1/projects/{project['id']}/agent/reviews/{review['id']}/refresh")
    assert response.status_code == 200, response.text
    fresh = response.json()
    assert fresh["id"] == review["id"]
    assert fresh["status"] == "draft"
    assert fresh["proposals"][0]["before"]["deadline"] == "2026-11-10"
    assert db_session.get(Task, audit.id).deadline == date(2026, 11, 10)
    assert db_session.query(Meeting).count() == 0
    assert db_session.query(AgentReview).count() == 1
