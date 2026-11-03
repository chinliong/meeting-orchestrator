"""The demo boards load into a working state: tasks, checklist, summaries and a valid pending review."""
import json

from app.api.agent import stale_details
from app.models.models import AgentReview, Meeting, Project, Subtask, Task, User
from app.seed import seed_demo_boards


def test_demo_boards_load_with_a_valid_pending_review(db_session):
    owner = User(email="demo@example.com", password_hash="x")
    db_session.add(owner)
    db_session.flush()
    added = seed_demo_boards(db_session, owner.id)
    db_session.commit()
    assert added == ["SAP Go-Live Workshops (demo)", "Mobile App Launch (demo)"]
    sap, app = (db_session.query(Project).filter_by(name=n).one() for n in added)
    assert db_session.query(Task).filter_by(project_id=sap.id).count() == 18
    assert db_session.query(Subtask).count() == 5
    assert all(m.summary for m in db_session.query(Meeting).all())
    # Every extracted task keeps its score and source, as on a real import.
    assert all(t.confidence is not None and t.source_decision for t in db_session.query(Task).all())

    review = db_session.query(AgentReview).one()
    assert review.project_id == app.id and review.status == "draft"
    plan = json.loads(review.plan_json)
    task_ids = {t.id for t in db_session.query(Task).filter_by(project_id=app.id)}
    assert all(p["task_id"] in task_ids for p in plan["proposals"] if p["kind"] == "update")
    assert all(p["duplicate_of"]["id"] in task_ids for p in plan["proposals"] if p.get("possible_duplicate"))
    # The suggested changes match the board they were made against, so all can be applied.
    assert stale_details(db_session, app.id, plan, json.loads(review.input_json)) == (None, [])

    # Seeding again adds nothing.
    assert seed_demo_boards(db_session, owner.id) == []
