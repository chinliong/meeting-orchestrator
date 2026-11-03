"""Feature-gated assistant API. Parsing adds new work; existing-task changes require approval."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.transcripts import EXTRACTION_FAILED, accept_audio, write_summary
from app.auth import get_optional_user, project_access_level, require_project_edit, require_project_view
from app.db import get_db
from app.llm import agent as agent_llm
from app.llm import assistant as assistant_llm
from app.llm.gemini import GeminiError
from app.llm.parser import TranscriptParser
from app.models.models import AgentReview, Attachment, Meeting, MeetingStatus, Project, Subtask, Task, TaskStatus, User
from app.ratelimit import (agent_ai_limit, agent_chat_limit, agent_parse_ai_limit, agent_review_ai_limit,
                           audio_limit, parse_limit)
from app.schemas.agent import ApplyInput, ChatInput, ReviewInput
from app.schemas.schemas import MeetingOut

log = logging.getLogger(__name__)


def enabled():
    return os.getenv("ENABLE_MEETING_AGENT", "false").strip().lower() == "true"


def require_enabled():
    if not enabled():
        raise HTTPException(404, "Meeting agent preview is not enabled.")


router = APIRouter(prefix="/projects/{project_id}/agent", tags=["meeting-agent"],
                   dependencies=[Depends(require_enabled)])


def board_snapshot(db: Session, project_id: int, lock=False):
    query = db.query(Task).filter(Task.project_id == project_id).order_by(Task.id)
    if lock:
        # Lock task rows before comparing the baseline. Existing edit endpoints update these
        # same rows. SQLite serializes writes via the review-state CAS before this read.
        query = query.with_for_update()
    tasks = query.all()
    result = []
    for t in tasks:
        result.append({"id": t.id, "description": t.description, "owner": t.owner,
                       "deadline": t.deadline.isoformat() if t.deadline else None,
                       "status": t.status.value, "meeting_id": t.meeting_id,
                       "meeting_title": t.meeting_title,
                       "meeting_date": t.meeting_date.isoformat() if t.meeting_date else None,
                       "source_decision": t.source_decision,
                       "subtask_total": t.subtask_total, "subtask_done": t.subtask_done,
                       "attachment_count": t.attachment_count})
    return result


def fingerprint(tasks):
    return hashlib.sha256(json.dumps(tasks, sort_keys=True).encode()).hexdigest()


def target_changed(proposal, tasks):
    task = tasks.get(proposal["task_id"])
    return task is None or agent_llm.fields_of(task) != proposal["before"]


def stale_details(db, project_id, plan, source, tasks=None):
    tasks = tasks if tasks is not None else {t["id"]: t for t in board_snapshot(db, project_id)}
    if plan.get("mode") == "meeting_updates":
        meeting = db.get(Meeting, plan.get("source_meeting_id"))
        if (meeting is None or meeting.project_id != project_id
                or meeting.transcript_text != source["transcript"]
                or not meeting.meeting_date or meeting.meeting_date.isoformat() != source["meeting_date"]):
            return "The source meeting was removed or changed. Ask the assistant for fresh suggestions.", [p["id"] for p in plan["proposals"]]
    unavailable = [p["id"] for p in plan["proposals"] if p["kind"] == "update" and target_changed(p, tasks)]
    unavailable.extend(p["id"] for p in plan["proposals"] if p["kind"] == "create"
                       and agent_llm.likely_duplicate(p["after"]["description"], list(tasks.values())))
    return ("Some suggested tasks changed or already exist. Unavailable suggestions need refreshing; other suggestions can still be applied."
            if unavailable else None), unavailable


def child_fingerprint(db, task_id):
    # Only tasks that undo would DELETE need child checks; editing a checklist on an
    # updated task is harmless because undo restores task fields, never its children.
    children = [[s.id, s.title, s.done, s.position] for s in db.query(Subtask).filter_by(task_id=task_id).order_by(Subtask.id).with_for_update()]
    files = [[a.id, a.filename, a.content_type, a.size, hashlib.sha256(a.data).hexdigest()]
             for a in db.query(Attachment).filter_by(task_id=task_id).order_by(Attachment.id).with_for_update()]
    return fingerprint({"subtasks": children, "attachments": files})


def duplicate_transcript(db, project_id, transcript):
    return db.query(Meeting).filter_by(project_id=project_id, transcript_text=transcript).order_by(Meeting.id.desc()).first()


def reject_duplicate(meeting):
    raise HTTPException(409, {"code": "duplicate_transcript", "message": "This transcript has already been added to this board.",
                              "meeting": {"id": meeting.id, "title": meeting.title,
                                          "created_at": meeting.created_at.isoformat() if meeting.created_at else None}})


def review_expired(review):
    return json.loads(review.plan_json).get("mode") != "meeting_updates" and review.expires_at < datetime.utcnow()


def output(review, db=None):
    plan = json.loads(review.plan_json)
    reason, unavailable = stale_details(db, review.project_id, plan, json.loads(review.input_json)) if db is not None and review.status == "draft" else (None, [])
    return {"stale": bool(reason), "stale_reason": reason, "unavailable_proposal_ids": unavailable, "id": review.id, "status": review.status,
            "mode": json.loads(review.plan_json).get("mode", "meeting"),
            "created_at": review.created_at.isoformat() + "Z",
            "expires_at": None if plan.get("mode") == "meeting_updates" else review.expires_at.isoformat() + "Z",
            "input": json.loads(review.input_json), **json.loads(review.plan_json),
            "receipt": json.loads(review.receipt_json) if review.receipt_json else None}


def load_review(db, project_id, review_id, user, token):
    require_project_edit(db, project_id, user, token)
    review = db.query(AgentReview).filter_by(id=review_id, project_id=project_id).first()
    if review is None:
        raise HTTPException(404, "Review not found in this project.")
    return review


def conflict(db, message):
    db.rollback()
    raise HTTPException(409, message)


def project_context(db, project, tasks):
    if len(tasks) > agent_llm.MAX_TASKS:
        raise HTTPException(422, "The preview supports boards with up to 200 tasks. Use a smaller project.")
    source_ids = {t["meeting_id"] for t in tasks if t["meeting_id"] is not None}
    source_ids.update(row[0] for row in db.query(Meeting.id).filter_by(
        project_id=project.id, status=MeetingStatus.COMPLETE).order_by(
        Meeting.created_at.desc(), Meeting.id.desc()).limit(30))
    meetings = {m.id: {"id": m.id, "title": m.title,
                      "meeting_date": (m.meeting_date or m.created_at.date()).isoformat(),
                      "transcript": m.transcript_text}
                for m in db.query(Meeting).filter(Meeting.project_id == project.id, Meeting.id.in_(source_ids))}
    board = {"project_name": project.name, "tasks": tasks,
             "meeting_scope": "Task source meetings and the 30 most recently added completed meetings.",
             "meetings": [{k: v for k, v in m.items() if k != "transcript"} for m in meetings.values()]}
    return board, meetings


@router.post("/chat")
@agent_chat_limit
@agent_ai_limit
def chat(request: Request, project_id: int, payload: ChatInput,
         user: Optional[User] = Depends(get_optional_user),
         x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    project = require_project_view(db, project_id, user, x_workspace_token)
    can_edit = project_access_level(project, user, x_workspace_token) == "edit"
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(503, "Configure GEMINI_API_KEY on the local backend to use the assistant.")
    payload._used_evidence = [json.loads(row[0])["transcript"] for row in db.query(AgentReview.input_json).filter(
        AgentReview.project_id == project_id).all() if json.loads(row[0]).get("title") == "Task changes from chat"]
    tasks = board_snapshot(db, project_id)
    board, meetings = project_context(db, project, tasks)
    db.rollback()
    try:
        answer = assistant_llm.run_chat(payload, board, meetings, can_edit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except GeminiError as exc:
        log.warning("assistant failed: %s", exc)
        raise HTTPException(502, "Gemini couldn't complete that answer. Your board has not changed. Please try again.") from exc
    db.expire_all()
    require_project_view(db, project_id, user, x_workspace_token)
    proposals = answer.pop("proposals")
    review = None
    if proposals:
        require_project_edit(db, project_id, user, x_workspace_token)
        plan = {"mode": "chat", "summary": answer["answer"][:2000], "proposals": proposals,
                **{k: answer[k] for k in ("questions", "model", "trace", "steps", "elapsed_seconds")}}
        source = {"title": "Task changes from chat", "meeting_date": payload.current_date.isoformat(),
                  "transcript": assistant_llm.user_evidence(payload), "instructions": ""}
        row = AgentReview(id=str(uuid.uuid4()), project_id=project_id, status="draft",
                          expires_at=datetime.utcnow() + timedelta(hours=1), input_json=json.dumps(source),
                          plan_json=json.dumps(plan), baseline_hash=fingerprint(tasks))
        db.add(row)
        db.commit()
        db.refresh(row)
        review = output(row)
    return {**answer, "review": review}


@router.get("/reviews")
def list_reviews(project_id: int, view: Literal["all", "pending", "history"] = "all", user: Optional[User] = Depends(get_optional_user),
                 x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    require_project_edit(db, project_id, user, x_workspace_token)
    # Meeting suggestions remain available until resolved; task-level checks protect apply.
    query = db.query(AgentReview).filter(AgentReview.project_id == project_id)
    if view == "pending":
        query = query.filter(AgentReview.status == "draft")
    elif view == "history":
        query = query.filter(AgentReview.status.in_(["applied", "undone"]))
    query = query.order_by(AgentReview.created_at.desc(), AgentReview.id.desc())
    rows = query.all() if view != "history" else query.limit(10).all()
    items = []
    tasks = {t["id"]: t for t in board_snapshot(db, project_id)} if view == "pending" else None
    for r in rows:
        if r.status == "draft" and review_expired(r):
            continue
        plan = json.loads(r.plan_json)
        # Removing a meeting also withdraws its unapproved changes from the toolbar.
        # Keep the stored audit details, but do not revive old orphaned drafts now
        # that meeting suggestions no longer expire.
        if view == "pending" and plan.get("mode") == "meeting_updates":
            source_meeting = db.get(Meeting, plan.get("source_meeting_id"))
            if source_meeting is None or source_meeting.project_id != project_id:
                continue
        proposals = plan["proposals"]
        if view == "pending" and not proposals:
            continue
        receipt = json.loads(r.receipt_json) if r.receipt_json else None
        mode = plan.get("mode", "meeting")
        # Chat changes share one generic title; name the first changed task instead.
        title = proposals[0]["after"]["description"] if mode == "chat" and proposals else json.loads(r.input_json)["title"]
        reason, _ = stale_details(db, project_id, plan, json.loads(r.input_json), tasks) if view == "pending" else (None, [])
        items.append({"stale": bool(reason), "stale_reason": reason, "id": r.id, "mode": mode, "title": title, "status": r.status,
                      "change_count": len(receipt["proposal_ids"]) if receipt else len(proposals),
                      "created_at": r.created_at.isoformat() + "Z"})
    return items if view == "pending" else items[:10]


@router.get("/reviews/{review_id}")
def get_review(project_id: int, review_id: str, user: Optional[User] = Depends(get_optional_user),
               x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    return output(load_review(db, project_id, review_id, user, x_workspace_token), db)


@router.post("/reviews", status_code=201)
@parse_limit
@agent_review_ai_limit
def create_review(request: Request, project_id: int, payload: ReviewInput,
                  user: Optional[User] = Depends(get_optional_user),
                  x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    return generate_review(project_id, payload, user, x_workspace_token, db)


def generate_review(project_id, payload, user, x_workspace_token, db, *, commit=True):
    project = require_project_edit(db, project_id, user, x_workspace_token)
    # Reject duplicate imports, including meetings added through the regular extraction flow.
    existing = duplicate_transcript(db, project_id, payload.transcript)
    if existing and payload.check_duplicate:
        reject_duplicate(existing)
    tasks, plan = run_meeting_review(db, project, payload)
    # Recheck access after the potentially long model call (e.g. link revoked meanwhile).
    db.expire_all()
    require_project_edit(db, project_id, user, x_workspace_token)
    review = store_meeting_review(db, project_id, payload, tasks, plan)
    if commit:
        db.commit()
    db.refresh(review)
    return output(review)


def extract_candidates(payload):
    """The meeting's tasks from the evaluated parser, which the assistant then reconciles."""
    try:
        extraction = TranscriptParser().parse(payload.transcript, meeting_date=payload.meeting_date)
    except Exception as exc:  # LLM/API failure: nothing is saved, as for a failed review
        log.warning("parser failed for assistant import: %s", exc)
        raise HTTPException(502, EXTRACTION_FAILED) from exc
    return [item.model_dump(mode="json") for item in extraction.action_items]


def with_candidates(plan, candidates, tasks=()):
    """Add the parser's candidates as new-task proposals, except those already on the board.

    They keep their extraction score and source decision, so the board treats them like any
    parsed task: a score below the review threshold still marks the card "Check this". Each
    candidate matched to an existing task is named in a note, so a wrong match can be noticed.
    """
    existing = {e["item"]: e["task_id"] for e in plan.get("existing_items", [])}
    by_id = {t["id"]: t for t in tasks}
    next_id = max((p["id"] for p in plan["proposals"]), default=-1) + 1
    for i, c in enumerate(candidates):
        if i in existing:
            match = by_id.get(existing[i])
            if match:
                plan["questions"].append(f'“{c["description"]}” is already on the board as “{match["description"]}”. '
                                         "No extra copy was added.")
            continue
        plan["proposals"].append({
            "id": next_id, "kind": "create", "task_id": None, "before": None,
            "after": {k: c[k] for k in ("description", "owner", "deadline", "status")},
            "evidence": c.get("source_decision") or "", "reason": "Extracted from the meeting.",
            "confidence": c["confidence"]})
        next_id += 1
    return plan


def run_meeting_review(db, project, payload):
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(503, "Configure GEMINI_API_KEY on the local backend to run the agent.")
    tasks = board_snapshot(db, project.id)
    board, meetings = project_context(db, project, tasks)
    # Do not keep a read transaction open while waiting for the model.
    db.rollback()
    candidates = extract_candidates(payload)
    if not tasks:
        # Nothing to reconcile: the parser's tasks are the result, exactly as evaluated.
        plan = {"summary": f"Extracted {len(candidates)} tasks from the meeting.", "proposals": [],
                "questions": [], "existing_items": [], "model": TranscriptParser()._resolved_model(),
                "trace": [{"label": f"Extracted {len(candidates)} tasks", "tool": "parser"}],
                "steps": 0, "elapsed_seconds": 0}
        return tasks, with_candidates(plan, candidates)
    try:
        plan = agent_llm.run_review(payload, board, meetings, candidates=candidates)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except GeminiError as exc:
        log.warning("agent review failed: %s", exc)
        raise HTTPException(502, "Gemini couldn't complete a valid review within its limits. No tasks changed. Try again.") from exc
    return tasks, with_candidates(plan, candidates, tasks)


def store_meeting_review(db, project_id, payload, tasks, plan):
    review = AgentReview(id=str(uuid.uuid4()), project_id=project_id, status="draft",
                         expires_at=datetime.utcnow() + timedelta(hours=1),
                         input_json=payload.model_dump_json(), plan_json=json.dumps(plan),
                         baseline_hash=fingerprint(tasks))
    db.add(review)
    db.flush()
    return review


def set_fields(task, fields):
    old_deadline = task.deadline.isoformat() if task.deadline else None
    for key in ("description", "owner", "deadline", "status"):
        value = fields[key]
        if key == "deadline" and value:
            value = date.fromisoformat(value)
        if key == "status":
            value = TaskStatus(value)
        setattr(task, key, value)
    # A changed deadline should be eligible for a fresh reminder.
    if old_deadline != fields["deadline"]:
        task.last_notified_for = None


@router.post("/reviews/{review_id}/apply")
def apply_review(project_id: int, review_id: str, payload: ApplyInput,
                 user: Optional[User] = Depends(get_optional_user),
                 x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    review = load_review(db, project_id, review_id, user, x_workspace_token)
    return apply_stored_review(db, project_id, review, payload.proposal_ids)


def apply_stored_review(db, project_id, review, proposal_ids, *, commit=True, recording_id=None):
    review_id = review.id
    selected = sorted(proposal_ids)
    if review.status == "applied":
        if json.loads(review.receipt_json)["proposal_ids"] != selected:
            raise HTTPException(409, "This review was already applied with a different selection.")
        return output(review)
    if review.status != "draft" or review_expired(review):
        raise HTTPException(409, "This review is no longer available to apply. Run a new review.")
    plan = json.loads(review.plan_json)
    if plan.get("mode") == "meeting_updates":
        source_meeting = db.get(Meeting, plan.get("source_meeting_id"))
        source = json.loads(review.input_json)
        if (source_meeting is None or source_meeting.project_id != project_id
                or source_meeting.transcript_text != source["transcript"]
                or not source_meeting.meeting_date
                or source_meeting.meeting_date.isoformat() != source["meeting_date"]):
            raise HTTPException(409, "The source meeting was removed or changed. These updates are no longer available.")
    if not selected and plan.get("mode", "meeting") != "meeting":
        raise HTTPException(422, "Select at least one task change.")
    proposals = [p for p in plan["proposals"] if p["id"] in selected]
    if len(proposals) != len(selected):
        raise HTTPException(422, "Select valid suggestions from this review.")
    db.flush()  # Persist a parse-only plan before expire_all discards ORM state.
    # Claim the draft in the same transaction as the board changes; concurrent retries cannot
    # create duplicates. Rollback restores draft on any failure.
    claimed = db.query(AgentReview).filter_by(id=review_id, status="draft").update(
        {"status": "applying"}, synchronize_session=False)
    if not claimed:
        conflict(db, "This review changed in another request. Reopen it to see the result.")
    db.expire_all()
    current = board_snapshot(db, project_id, lock=True)
    by_id = {t["id"]: t for t in current}
    for p in proposals:
        if p["kind"] == "update" and target_changed(p, by_id):
            conflict(db, "A task you selected has changed. Ask the assistant for fresh suggestions for that task.")
        if p["kind"] == "create" and agent_llm.likely_duplicate(p["after"]["description"], current):
            conflict(db, "A similar task was added while these suggestions were being prepared. Ask the assistant to check that task.")
    source = json.loads(review.input_json)
    meeting = None
    if plan.get("mode", "meeting") == "meeting":
        if recording_id is not None:
            meeting = db.query(Meeting).filter_by(id=recording_id, project_id=project_id).with_for_update().first()
            if meeting is None:
                conflict(db, "This recording was removed while it was being processed.")
            if meeting.status != MeetingStatus.PROCESSING or meeting.transcript_text != source["transcript"]:
                conflict(db, "This recording changed while it was being processed.")
            meeting.status = MeetingStatus.COMPLETE
        else:
            existing = duplicate_transcript(db, project_id, source["transcript"])
            if existing and source.get("check_duplicate", True):
                db.rollback()
                reject_duplicate(existing)
            meeting = Meeting(project_id=project_id, title=source["title"], transcript_text=source["transcript"],
                              meeting_date=date.fromisoformat(source["meeting_date"]), status=MeetingStatus.COMPLETE)
            db.add(meeting)
        db.flush()
    changes = []
    for p in proposals:
        if p["kind"] == "create":
            # Parser-extracted tasks keep their score. A task the assistant proposed from chat has
            # none, and stores none rather than a default 1.0 that would read as "100% confident".
            task = Task(project_id=project_id, meeting_id=meeting.id if meeting else None,
                        confidence=p.get("confidence"), source_decision=p["evidence"] or None)
            db.add(task)
        else:
            task = db.get(Task, p["task_id"])
        previous_reminder = task.last_notified_for
        set_fields(task, p["after"])
        db.flush()
        changes.append({"task_id": task.id, "kind": p["kind"], "before": p["before"], "after": p["after"],
                        "child_hash": child_fingerprint(db, task.id) if p["kind"] == "create" else None,
                        "last_notified_for": previous_reminder.isoformat() if previous_reminder else None})
    db.expire_all()
    receipt = {"version": 2, "proposal_ids": selected, "meeting_id": meeting.id if meeting else None, "changes": changes,
               "after_hash": fingerprint(board_snapshot(db, project_id)),
               "applied_at": datetime.utcnow().isoformat() + "Z"}
    review.status = "applied"
    review.receipt_json = json.dumps(receipt)
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(review)
    return output(review)


@router.post("/parse", status_code=201)
@parse_limit
@agent_parse_ai_limit
def parse_with_assistant(request: Request, project_id: int, payload: ReviewInput, background_tasks: BackgroundTasks,
                         user: Optional[User] = Depends(get_optional_user),
                         x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    generated = generate_review(project_id, payload, user, x_workspace_token, db, commit=False)
    review = load_review(db, project_id, generated["id"], user, x_workspace_token)
    result = finish_meeting_import(db, review)
    background_tasks.add_task(write_summary, result["meeting_id"])
    return result


def finish_meeting_import(db, review, *, recording_id=None):
    """Both transcript sources save new work and withhold existing-task updates atomically."""
    project_id = review.project_id
    plan = json.loads(review.plan_json)
    # Serialize imports for this project after Gemini returns, without holding a lock
    # across the paid call. Reconcile with CURRENT tasks; unrelated edits are harmless.
    db.query(Project).filter_by(id=project_id).with_for_update().first()
    current = board_snapshot(db, project_id, lock=True)
    by_id = {t["id"]: t for t in current}
    creates, updates, questions = [], [], list(plan["questions"])
    for proposal in plan["proposals"]:
        if proposal["kind"] == "update":
            if target_changed(proposal, by_id):
                questions.append(f'“{proposal["after"]["description"]}” changed while parsing. Its update was withheld; ask the assistant to check it again.')
            else:
                updates.append(proposal)
        else:
            match = agent_llm.likely_duplicate(proposal["after"]["description"], current)
            if match:
                questions.append(f'“{proposal["after"]["description"]}” looks like “{match["description"]}”, already on the board. No extra copy was added.')
            else:
                creates.append(proposal)
                current.append({"description": proposal["after"]["description"]})
    plan["questions"] = questions
    # The Parse transcript action authorizes adding this meeting and its NEW tasks.
    # Existing-task updates are kept in a separate draft with a post-import baseline.
    review.plan_json = json.dumps({**plan, "proposals": creates})
    imported = apply_stored_review(db, project_id, review, [p["id"] for p in creates], commit=False,
                                  recording_id=recording_id)
    pending = None
    if updates:
        pending = AgentReview(id=str(uuid.uuid4()), project_id=project_id, status="draft",
                              expires_at=datetime.utcnow() + timedelta(hours=1),
                              input_json=review.input_json,
                              plan_json=json.dumps({**plan, "mode": "meeting_updates", "proposals": updates,
                                                    "source_meeting_id": imported["receipt"]["meeting_id"]}),
                              baseline_hash=fingerprint(board_snapshot(db, project_id)))
        db.add(pending)
    # Saving the meeting, new tasks and pending updates is one atomic transaction.
    db.commit()
    if pending:
        db.refresh(pending)
    return {"meeting_id": imported["receipt"]["meeting_id"], "new_task_count": len(creates), "saved_review": imported,
            "review": output(pending) if pending else None, "questions": plan["questions"]}


def parse_recording_with_assistant(db, meeting):
    """Called only by an upload job that was authorized when the recording was accepted."""
    meeting_id, project_id = meeting.id, meeting.project_id
    payload = ReviewInput(title=meeting.title, meeting_date=meeting.meeting_date,
                          transcript=meeting.transcript_text, check_duplicate=False)
    project = db.get(Project, project_id)
    tasks, plan = run_meeting_review(db, project, payload)
    # The board may have been deleted during the model call. Do not leave orphaned reviews.
    db.expire_all()
    if db.get(Meeting, meeting_id) is None:
        return
    review = store_meeting_review(db, project_id, payload, tasks, plan)
    finish_meeting_import(db, review, recording_id=meeting_id)


@router.post("/recordings", response_model=MeetingOut, status_code=201)
@audio_limit
@parse_limit
@agent_parse_ai_limit
async def upload_recording(request: Request, project_id: int, background_tasks: BackgroundTasks,
                           title: str = Form(""), meeting_date: str = Form(""), file: UploadFile = File(...),
                           user: Optional[User] = Depends(get_optional_user),
                           x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    return await accept_audio(background_tasks, project_id, title, meeting_date, file,
                              user, x_workspace_token, db, use_assistant=True)


@router.get("/recordings/{meeting_id}/result")
def recording_result(project_id: int, meeting_id: int, user: Optional[User] = Depends(get_optional_user),
                     x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    require_project_edit(db, project_id, user, x_workspace_token)
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or meeting.project_id != project_id:
        raise HTTPException(404, "Recording not found in this project.")
    saved, pending = None, None
    for review in db.query(AgentReview).filter_by(project_id=project_id):
        plan = json.loads(review.plan_json)
        receipt = json.loads(review.receipt_json) if review.receipt_json else None
        if receipt and receipt.get("meeting_id") == meeting_id:
            saved = review
        elif plan.get("source_meeting_id") == meeting_id and review.status == "draft":
            pending = review
    if saved is None:
        raise HTTPException(409, "This recording has no completed assistant import.")
    saved_output = output(saved)
    return {"meeting_id": meeting_id, "new_task_count": len(saved_output["receipt"]["proposal_ids"]),
            "saved_review": saved_output, "review": output(pending, db) if pending else None,
            "questions": saved_output["questions"]}


@router.post("/reviews/{review_id}/refresh")
@agent_ai_limit
def refresh_review(request: Request, project_id: int, review_id: str,
                   user: Optional[User] = Depends(get_optional_user),
                   x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    review = load_review(db, project_id, review_id, user, x_workspace_token)
    if review.status != "draft":
        raise HTTPException(409, "These suggested changes have already been resolved.")
    original_plan = review.plan_json
    plan, source = json.loads(original_plan), json.loads(review.input_json)
    if plan.get("mode") == "meeting":
        raise HTTPException(409, "Add a new transcript using New meeting.")
    project = require_project_edit(db, project_id, user, x_workspace_token)
    if plan.get("mode") == "meeting_updates":
        reason, _ = stale_details(db, project_id, plan, source)
        if reason and reason.startswith("The source meeting"):
            raise HTTPException(409, "This meeting was removed or edited. Add the correct transcript using New meeting.")
    tasks = board_snapshot(db, project_id)
    board, meetings = project_context(db, project, tasks)
    mode = plan.get("mode", "chat")
    allowed_ids = {p["task_id"] for p in plan["proposals"] if p["kind"] == "update"}
    db.rollback()
    try:
        if mode == "meeting_updates":
            payload = ReviewInput.model_validate(source)
            fresh = agent_llm.run_review(payload, board, meetings)
            # Refreshing a saved meeting never reimports work or changes additional tasks.
            fresh["proposals"] = [p for p in fresh["proposals"] if p["kind"] == "update" and p["task_id"] in allowed_ids]
            if allowed_ids - {task["id"] for task in tasks}:
                fresh["questions"].append("A task from these suggested changes was removed. Use Add task if you want to recreate it.")
        else:
            # Stored user evidence is explicitly renewed by clicking Refresh. It was
            # validated on the original request and remains bounded by the context budget.
            payload = ChatInput.model_construct(message=source["transcript"], current_date=date.fromisoformat(source["meeting_date"]), history=[])
            fresh = assistant_llm.run_chat(payload, board, meetings, True)
            fresh = {"summary": fresh["answer"][:2000], **{k: fresh[k] for k in
                     ("proposals", "questions", "model", "trace", "steps", "elapsed_seconds")}}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except GeminiError as exc:
        log.warning("refresh failed: %s", exc)
        raise HTTPException(502, "Couldn’t refresh suggested changes. Please try again.") from exc
    db.expire_all()
    require_project_edit(db, project_id, user, x_workspace_token)
    if mode == "meeting_updates":
        reason, _ = stale_details(db, project_id, plan, source)
        if reason and reason.startswith("The source meeting"):
            raise HTTPException(409, "The meeting changed while refreshing. Add the correct transcript using New meeting.")
    updated = db.query(AgentReview).filter_by(id=review_id, project_id=project_id, status="draft", plan_json=original_plan).update({
        "plan_json": json.dumps({**fresh, "mode": mode, **({"source_meeting_id": plan["source_meeting_id"]} if mode == "meeting_updates" else {})}),
        "baseline_hash": fingerprint(tasks), "expires_at": datetime.utcnow() + timedelta(hours=1),
    }, synchronize_session=False)
    if not updated:
        conflict(db, "These suggested changes were resolved elsewhere. Reopen them to see the result.")
    db.commit()
    db.refresh(review)
    return output(review, db)


@router.post("/reviews/{review_id}/undo")
def undo_review(project_id: int, review_id: str, user: Optional[User] = Depends(get_optional_user),
                x_workspace_token: Optional[str] = Header(None), db: Session = Depends(get_db)):
    review = load_review(db, project_id, review_id, user, x_workspace_token)
    if review.status == "undone":
        return output(review)
    if review.status != "applied":
        raise HTTPException(409, "Only an applied review can be undone.")
    claimed = db.query(AgentReview).filter_by(id=review_id, status="applied").update(
        {"status": "undoing"}, synchronize_session=False)
    if not claimed:
        conflict(db, "This review changed in another request. Reopen it to see the result.")
    db.expire_all()
    receipt = json.loads(review.receipt_json)
    current = {t["id"]: t for t in board_snapshot(db, project_id, lock=True)}
    if receipt.get("version") == 2:
        for change in receipt["changes"]:
            task = current.get(change["task_id"])
            if task is None or agent_llm.fields_of(task) != change["after"]:
                conflict(db, "A task changed since this action. Undo would overwrite newer work.")
            if change["kind"] == "create" and child_fingerprint(db, task["id"]) != change["child_hash"]:
                conflict(db, "A task added by this import has new or edited subtasks or attachments. Undo would remove that work.")
        if receipt["meeting_id"] is not None:
            actual = {t["id"] for t in current.values() if t["meeting_id"] == receipt["meeting_id"]}
            expected = {c["task_id"] for c in receipt["changes"] if c["kind"] == "create"}
            if actual != expected:
                conflict(db, "This meeting has additional tasks. Undo would remove newer work.")
    elif fingerprint(list(current.values())) != receipt["after_hash"]:
        conflict(db, "The board changed since these suggestions were applied. Undo would overwrite newer work.")
    for change in receipt["changes"]:
        if change["kind"] == "update":
            task = db.get(Task, change["task_id"])
            set_fields(task, change["before"])
            task.last_notified_for = date.fromisoformat(change["last_notified_for"]) if change["last_notified_for"] else None
    if receipt["meeting_id"] is not None:
        meeting = db.get(Meeting, receipt["meeting_id"])
        if meeting is None:
            conflict(db, "The saved meeting was removed. This review can no longer be undone.")
        source = json.loads(review.input_json)
        if (meeting.title != source["title"] or meeting.transcript_text != source["transcript"]
                or not meeting.meeting_date or meeting.meeting_date.isoformat() != source["meeting_date"]):
            conflict(db, "The saved meeting changed. Undo would remove newer work.")
        db.delete(meeting)  # Cascades only to tasks created by this review.
    else:
        for change in receipt["changes"]:
            if change["kind"] == "create":
                db.delete(db.get(Task, change["task_id"]))
    review.status = "undone"
    db.commit()
    db.refresh(review)
    return output(review)
