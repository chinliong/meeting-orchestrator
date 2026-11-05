"""How well the meeting agent reconciles a follow-up meeting with the board, scored against an answer key.

In the app the parser extracts a meeting's tasks and the agent reconciles them with the board
(backend/app/llm/agent.py): it marks which extracted tasks are already on the board, and suggests
changes to existing tasks. eval/agent_eval.py measured extraction; this measures reconciliation.

Each scenario in data/reconciliation-scenarios/ continues one of the short test meetings. The
board holds that meeting's annotated tasks; the follow-up meeting is new. The agent is given the
follow-up's extracted tasks from the answer key rather than from the parser, so the score is of
reconciliation alone, not of extraction errors passed along. Its review is the one the app makes,
through the same function, rules and checks.

What is scored:

* Repeats: an extracted task the agent marks as already on the board, against the expected
  board task. A new task marked as a repeat would be held back from the board, so it counts
  against precision. "App" figures add the app's wording check against the board
  (likely_duplicate), which also holds back near-identical wording the agent did not mark. (The
  app also applies it between a meeting's own new tasks; no scenario has two such tasks.)
* Updates: the board tasks it suggests changing, and each changed owner, deadline or status
  against the answer key. A change the key does not expect is a wrong change. Owners are compared
  by first name, as in the parser evaluation, so "Priya Nair" and "Priya" are the same person.
  Rewording a description is reported but not scored, as the answer key does not fix a wording.
* A review that cannot be finished within the agent's limits shows the user an error and
  suggests nothing, so it scores as nothing found.

Usage (from the repo root, with the backend virtualenv active):

    python -m eval.reconcile_eval --simulate        # free: a stand-in model that answers from the key
    python -m eval.reconcile_eval --run             # calls Gemini: one review per scenario, 1-6 calls each
    python -m eval.reconcile_eval --write-report    # free: scores the saved run
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

from eval.run_eval import REPO_ROOT, _norm_owner  # also puts backend/ on sys.path and loads backend/.env

from app.llm import agent, gemini  # noqa: E402
from app.schemas.agent import ReviewInput  # noqa: E402

SCENARIO_DIR = REPO_ROOT / "data" / "reconciliation-scenarios"
BASE_TRANSCRIPTS = REPO_ROOT / "data" / "synthetic-transcripts"
BASE_ANNOTATIONS = REPO_ROOT / "data" / "annotated-test-set" / "annotations.json"
PREDICTIONS = REPO_ROOT / "eval" / "reconcile_predictions.json"
RESULTS_JSON = REPO_ROOT / "eval" / "reconcile_results.json"
REPORT_MD = REPO_ROOT / "docs" / "reconciliation-evaluation.md"
FIELDS = ("owner", "deadline", "status")
TASK_ID_BASE = 100  # board task i has id 100 + i
SOURCE_MEETING_ID = 1
API_ATTEMPTS = 3


def load_scenarios() -> list[dict]:
    return json.loads((SCENARIO_DIR / "scenarios.json").read_text())


def meeting_title(transcript: str) -> str:
    return next(line.split(":", 1)[1].strip() for line in transcript.splitlines() if line.startswith("Meeting:"))


def board_for(scenario: dict) -> tuple[dict, dict[int, dict]]:
    """The context the app builds for the board (api/agent.py: board_snapshot, project_context)."""
    base = next(m for m in json.loads(BASE_ANNOTATIONS.read_text()) if m["transcript_file"] == scenario["base_transcript"])
    transcript = (BASE_TRANSCRIPTS / scenario["base_transcript"]).read_text()
    title = meeting_title(transcript)
    tasks = [{"id": TASK_ID_BASE + i, "description": t["description"][:1].upper() + t["description"][1:],
              "owner": t["owner"], "deadline": t["deadline"], "status": t["status"],
              "meeting_id": SOURCE_MEETING_ID, "meeting_title": title, "meeting_date": base["meeting_date"],
              "source_decision": None, "subtask_total": 0, "subtask_done": 0, "attachment_count": 0}
             for i, t in enumerate(base["expected_action_items"])]
    meetings = {SOURCE_MEETING_ID: {"id": SOURCE_MEETING_ID, "title": title, "meeting_date": base["meeting_date"],
                                    "transcript": transcript}}
    board = {"project_name": "Evaluation", "tasks": tasks,
             "meeting_scope": "Task source meetings and the 30 most recently added completed meetings.",
             "meetings": [{k: v for k, v in m.items() if k != "transcript"} for m in meetings.values()]}
    return board, meetings


def candidates_for(scenario: dict) -> list[dict]:
    """The follow-up's tasks as the parser hands them over (api/agent.py: extract_candidates)."""
    return [{**c, "confidence": 0.9, "source_decision": None} for c in scenario["candidates"]]


def review_one(scenario: dict) -> dict:
    board, meetings = board_for(scenario)
    payload = ReviewInput(title=scenario["title"], meeting_date=date.fromisoformat(scenario["meeting_date"]),
                          transcript=(SCENARIO_DIR / scenario["transcript_file"]).read_text())
    block = {"id": scenario["id"], "existing_items": [], "updates": [], "questions": []}
    for attempt in range(API_ATTEMPTS):
        try:
            plan = agent.run_review(payload, board, meetings, candidates=candidates_for(scenario))
        except gemini.GeminiError as exc:
            if str(exc).startswith("Gemini request failed") and attempt < API_ATTEMPTS - 1:
                time.sleep(20 * (attempt + 1))
                continue
            # A request Gemini never answered is excluded; a review it could not finish is an
            # error the user would see, so it scores as nothing found.
            block["error"] = "api" if str(exc).startswith("Gemini request failed") else "limit"
            block["error_message"] = str(exc)[:200]
            return block
        block["existing_items"] = [[e["item"], e["task_id"]] for e in plan["existing_items"]]
        block["updates"] = [{"task_id": p["task_id"], "before": p["before"], "after": p["after"], "evidence": p["evidence"]}
                            for p in plan["proposals"] if p["kind"] == "update"]
        block["questions"] = plan["questions"]
        block["steps"] = plan["steps"]
        block["model"] = plan["model"]
        return block
    return block


def run(save_to: Path) -> dict:
    scenarios = load_scenarios()
    blocks = []
    for s in scenarios:
        b = review_one(s)
        note = f"  [{b['error'].upper()}: {b.get('error_message', '')[:60]}]" if b.get("error") else ""
        print(f"  {s['id']:22} {len(b['existing_items'])} repeats, {len(b['updates'])} updates, "
              f"{len(b['questions'])} questions{note}", flush=True)
        blocks.append(b)
    out = {"note": "Meeting-agent reconciliation reviews; see eval/reconcile_eval.py.", "scenarios": blocks}
    save_to.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return out


def oracle_turn(scenario: dict):
    """A stand-in model that submits the answer key, so a free run checks the whole pipeline and
    that every expected update passes the app's own checks (exact quote, owner named)."""
    board, _ = board_for(scenario)
    proposals = []
    for u in scenario["expected"]["updates"]:
        task = board["tasks"][u["task"]]
        proposals.append({"kind": "update", "task_id": task["id"],
                          "after": {**{k: task[k] for k in ("description", *FIELDS)}, **u["changes"]},
                          "evidence": u["quote"], "reason": "From the answer key."})
    args = {"summary": "Answer key.", "proposals": proposals, "questions": [],
            "existing_items": [{"item": c, "task_id": TASK_ID_BASE + t} for c, t in scenario["expected"]["existing"]]}
    return lambda *a, **k: {"role": "model", "parts": [{"functionCall": {"name": "finish_review", "args": args}}]}


def simulate() -> dict:
    real = agent.model_turn
    try:
        blocks = []
        for s in load_scenarios():
            agent.model_turn = oracle_turn(s)
            blocks.append(review_one(s))
    finally:
        agent.model_turn = real
    return {"note": "Simulated: a stand-in model answering from the key.", "scenarios": blocks}


def same_value(field: str, got, expected) -> bool:
    if field == "owner":
        return got is not None and expected is not None and _norm_owner(got) == _norm_owner(expected)
    return got == expected


def ratio(num: int, den: int):
    return round(num / den, 3) if den else None


def f1(p, r):
    return round(2 * p * r / (p + r), 3) if p and r else (0.0 if p is not None and r is not None else None)


def score(predictions: dict, scenarios: list[dict] | None = None) -> dict:
    scenarios = scenarios or load_scenarios()
    by_id = {b["id"]: b for b in predictions["scenarios"]}
    t = {k: 0 for k in ("rep_expected", "rep_predicted", "rep_correct", "rep_new_held", "app_predicted", "app_correct",
                        "app_new_held", "upd_expected", "upd_predicted", "upd_correct_task", "upd_exact",
                        "fld_expected", "fld_predicted", "fld_correct", "wrong_changes", "description_rewords",
                        "reviews", "failed", "api_errors", "steps", "questions")}
    per = []
    for s in scenarios:
        b = by_id.get(s["id"], {"existing_items": [], "updates": [], "questions": [], "error": "missing"})
        if b.get("error") == "api":
            t["api_errors"] += 1
            continue
        t["reviews"] += 1
        t["failed"] += b.get("error") in ("limit", "missing")
        t["steps"] += b.get("steps", 0)
        t["questions"] += len(b.get("questions", []))
        board, _ = board_for(s)
        new = set(s["expected"]["new_candidates"])
        gold_pairs = {(c, TASK_ID_BASE + i) for c, i in s["expected"]["existing"]}
        pairs = {tuple(p) for p in b["existing_items"]}
        # The app also holds back a new task whose wording nearly matches one on the board.
        app_pairs = set(pairs)
        marked = {c for c, _ in pairs}
        for c, cand in enumerate(s["candidates"]):
            if c not in marked:
                match = agent.likely_duplicate(cand["description"], board["tasks"])
                if match:
                    app_pairs.add((c, match["id"]))
        t["rep_expected"] += len(gold_pairs)
        t["rep_predicted"] += len(pairs)
        t["rep_correct"] += len(pairs & gold_pairs)
        t["rep_new_held"] += sum(c in new for c, _ in pairs)
        t["app_predicted"] += len(app_pairs)
        t["app_correct"] += len(app_pairs & gold_pairs)
        t["app_new_held"] += sum(c in new for c, _ in app_pairs)

        gold_updates = {TASK_ID_BASE + u["task"]: u["changes"] for u in s["expected"]["updates"]}
        t["upd_expected"] += len(gold_updates)
        t["fld_expected"] += sum(len(c) for c in gold_updates.values())
        exact = 0
        for u in b["updates"]:
            changed = {f: u["after"][f] for f in FIELDS if u["after"][f] != u["before"][f]}
            t["description_rewords"] += u["after"]["description"] != u["before"]["description"]
            if not changed:
                continue  # a rewording only
            t["upd_predicted"] += 1
            t["fld_predicted"] += len(changed)
            gold = gold_updates.get(u["task_id"], {})
            if gold:
                t["upd_correct_task"] += 1
            right = sum(f in gold and same_value(f, v, gold[f]) for f, v in changed.items())
            t["fld_correct"] += right
            t["wrong_changes"] += len(changed) - right
            exact += changed.keys() == gold.keys() and right == len(gold)
        t["upd_exact"] += exact
        per.append({"id": s["id"], "repeats": f"{len(pairs & gold_pairs)}/{len(gold_pairs)}",
                    "new_held_back": sum(c in new for c, _ in pairs),
                    "updates_exact": f"{exact}/{len(gold_updates)}",
                    "wrong_changes": sum(1 for u in b["updates"] for f in FIELDS
                                         if u["after"][f] != u["before"][f]
                                         and not (f in gold_updates.get(u["task_id"], {})
                                                  and same_value(f, u["after"][f], gold_updates[u["task_id"]][f]))),
                    "failed": b.get("error") in ("limit", "missing")})

    rp, rr = ratio(t["rep_correct"], t["rep_predicted"]), ratio(t["rep_correct"], t["rep_expected"])
    ap, ar = ratio(t["app_correct"], t["app_predicted"]), ratio(t["app_correct"], t["rep_expected"])
    up, ur = ratio(t["upd_correct_task"], t["upd_predicted"]), ratio(t["upd_correct_task"], t["upd_expected"])
    fp, fr = ratio(t["fld_correct"], t["fld_predicted"]), ratio(t["fld_correct"], t["fld_expected"])
    return {
        "repeats": {"agent": {"precision": rp, "recall": rr, "f1": f1(rp, rr), "new_tasks_held_back": t["rep_new_held"]},
                    "app": {"precision": ap, "recall": ar, "f1": f1(ap, ar), "new_tasks_held_back": t["app_new_held"]},
                    "expected": t["rep_expected"], "new_tasks": sum(len(s["expected"]["new_candidates"]) for s in scenarios)},
        "updates": {"tasks": {"precision": up, "recall": ur, "f1": f1(up, ur)},
                    "fields": {"precision": fp, "recall": fr, "f1": f1(fp, fr)},
                    "exact": t["upd_exact"], "expected_tasks": t["upd_expected"], "expected_fields": t["fld_expected"],
                    "wrong_changes": t["wrong_changes"], "description_rewords": t["description_rewords"]},
        "reviews": {"scored": t["reviews"], "not_completed": t["failed"], "provider_errors_excluded": t["api_errors"],
                    "mean_steps": round(t["steps"] / max(1, t["reviews"] - t["failed"]), 2),
                    "questions": t["questions"],
                    "model": next((b.get("model") for b in predictions["scenarios"] if b.get("model")), None)},
        "per_scenario": per,
    }


def pct(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def render(r: dict) -> str:
    rep, upd, rev = r["repeats"], r["updates"], r["reviews"]
    lines = [
        "# Meeting-agent reconciliation evaluation",
        "",
        "Generated by `python -m eval.reconcile_eval --write-report` from `eval/reconcile_predictions.json`.",
        "Each of the eight scenarios in `data/reconciliation-scenarios/` continues one of the short test",
        "meetings: the board holds that meeting's annotated tasks, and a follow-up meeting is reviewed",
        "against it. The agent receives the follow-up's tasks from the answer key, so this scores",
        "reconciliation alone: which tasks are already on the board, and which existing tasks change.",
        "",
        f"## Repeated tasks ({rep['expected']} of the extracted tasks repeat a board task; {rep['new_tasks']} are new)",
        "",
        "| | Precision | Recall | F1 | New tasks held back |",
        "|---|---|---|---|---|",
        f"| Agent | {pct(rep['agent']['precision'])} | {pct(rep['agent']['recall'])} | {pct(rep['agent']['f1'])} | {rep['agent']['new_tasks_held_back']} |",
        f"| App (agent and wording check) | {pct(rep['app']['precision'])} | {pct(rep['app']['recall'])} | {pct(rep['app']['f1'])} | {rep['app']['new_tasks_held_back']} |",
        "",
        "A task held back is not lost: it waits under Changes as a possible duplicate, one tick to add.",
        "",
        f"## Updates to existing tasks ({upd['expected_tasks']} expected, changing {upd['expected_fields']} owner, deadline or status values)",
        "",
        "| | Precision | Recall | F1 |",
        "|---|---|---|---|",
        f"| Tasks changed | {pct(upd['tasks']['precision'])} | {pct(upd['tasks']['recall'])} | {pct(upd['tasks']['f1'])} |",
        f"| Values changed | {pct(upd['fields']['precision'])} | {pct(upd['fields']['recall'])} | {pct(upd['fields']['f1'])} |",
        "",
        f"Suggestions exactly as expected: {upd['exact']} of {upd['expected_tasks']}. Changes the key does not expect: "
        f"{upd['wrong_changes']}. Descriptions reworded (not scored): {upd['description_rewords']}.",
        "",
        "## Per scenario",
        "",
        "| Scenario | Repeats found | New tasks held back | Updates exactly right | Unexpected changes |",
        "|---|---|---|---|---|",
        *[f"| {p['id']}{' (not completed)' if p['failed'] else ''} | {p['repeats']} | {p['new_held_back']} | "
          f"{p['updates_exact']} | {p['wrong_changes']} |" for p in r["per_scenario"]],
        "",
        f"Reviews: {rev['scored']}; not completed within limits: {rev['not_completed']}; provider errors excluded: "
        f"{rev['provider_errors_excluded']}; model calls per review: {rev['mean_steps']}; questions asked: "
        f"{rev['questions']}. Model: {rev['model']}.",
        "",
        "## Reading this",
        "",
        "One run of eight scenarios with one annotator; the scenarios were written for this test, after the",
        "agent was built. Each changed owner, deadline or status is a value; a suggestion is exactly right",
        "when it changes the expected values and nothing else. Owners are compared by first name, as in the",
        "parser evaluation. Every suggestion still needs the user's approval in the app, so a wrong one",
        "costs a dismissal, not a wrong board.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run", action="store_true", help="review every scenario with the agent (calls Gemini)")
    ap.add_argument("--simulate", action="store_true", help="free: a stand-in model answers from the key")
    ap.add_argument("--write-report", action="store_true")
    args = ap.parse_args()
    if args.simulate:
        preds = simulate()
        r = score(preds)
        print(json.dumps({k: r[k] for k in ("repeats", "updates", "reviews")}, indent=1))
        return
    if args.run:
        run(PREDICTIONS)
    if not PREDICTIONS.exists():
        raise SystemExit("No saved run. Use --run (calls Gemini) or --simulate (free).")
    r = score(json.loads(PREDICTIONS.read_text()))
    RESULTS_JSON.write_text(json.dumps(r, indent=1) + "\n")
    print(json.dumps({k: r[k] for k in ("repeats", "updates", "reviews")}, indent=1))
    if args.write_report:
        REPORT_MD.write_text(render(r))
        print(f"wrote {REPORT_MD.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
