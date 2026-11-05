"""Extraction quality of the meeting agent, scored against the same answer keys as the parser.

The agent (backend/app/llm/agent.py) reads a meeting against the board and proposes task changes.
On an empty board every proposal is a new task, so its first import of a meeting is the same job
the parser does, and can be scored the same way: the same annotated test sets, the same overlap
matcher, the same field checks (eval/run_eval.py). Its tasks are compared with the implemented
parser configuration, `gemini_prod`, read from the parser's own prediction caches, so the parser
is not re-run and its published figures are unchanged.

What counts:

* A new-task proposal is a predicted item. Its quote becomes the item's source.
* Items the agent withholds as a question (an ambiguous point, or a likely duplicate) are not
  tasks, exactly as in the app, so they count as missed.
* A review that cannot be completed within the agent's limits shows the user an error and adds
  nothing, so it is scored as finding nothing. A request the provider never answered (HTTP error,
  network) says nothing about quality and is excluded, as in parse_run.

Usage (from the repo root, with the backend virtualenv active):

    python -m eval.agent_eval --parse --runs 8 --set both   # calls Gemini: 8 runs x 8 meetings
    python -m eval.agent_eval --write-report                # free: scores the caches

The page it writes, docs/agent-evaluation.md, also holds Part 2, the reconciliation test
(eval/reconcile_eval.py), rendered from that test's saved run.
"""
from __future__ import annotations

import argparse
import json
import statistics as stats
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from eval.run_eval import (  # also puts backend/ on sys.path and loads backend/.env
    DEADLINE_TOLERANCE_DAYS,
    REPO_ROOT,
    TEST_SETS,
    permutation_test,
    runs_with,
    score_condition,
)

from eval.reconcile_eval import PREDICTIONS, render_section, score  # noqa: E402

from app.llm import agent, gemini  # noqa: E402
from app.schemas.agent import ReviewInput  # noqa: E402

AGENT_CACHES = {"short": REPO_ROOT / "eval" / "agent_predictions.json",
                "long": REPO_ROOT / "eval" / "agent_predictions_long.json"}
RESULTS_JSON = REPO_ROOT / "eval" / "agent_results.json"
REPORT_MD = REPO_ROOT / "docs" / "agent-evaluation.md"
PARSER = "gemini_prod"
METRICS = ("precision", "recall", "f1", "owner_accuracy", "status_accuracy", "deadline_exact_accuracy",
           f"deadline_within_{DEADLINE_TOLERANCE_DAYS}d_accuracy")
API_ATTEMPTS = 3
WORKERS = 4


def empty_board() -> dict:
    """The context the app gives the agent for a board with no tasks or meetings yet."""
    return {"project_name": "Evaluation", "tasks": [],
            "meeting_scope": "Task source meetings and the 30 most recently added completed meetings.",
            "meetings": []}


def review_one(transcript_dir: Path, entry: dict) -> dict:
    """One agent review of one meeting on an empty board, as a scorable block."""
    payload = ReviewInput(title=Path(entry["transcript_file"]).stem.replace("-", " ").title(),
                          meeting_date=date.fromisoformat(entry["meeting_date"]),
                          transcript=(transcript_dir / entry["transcript_file"]).read_text())
    block = {"transcript_file": entry["transcript_file"], "predicted": [], "questions": []}
    for attempt in range(API_ATTEMPTS):
        try:
            plan = agent.run_review(payload, empty_board(), {})
        except gemini.GeminiError as exc:
            if str(exc).startswith("Gemini request failed") and attempt < API_ATTEMPTS - 1:
                time.sleep(20 * (attempt + 1))
                continue
            # A request Gemini never answered is excluded; a review it could not finish is a
            # failure the user would see, so it is scored as finding nothing.
            block["error"] = "api" if str(exc).startswith("Gemini request failed") else "limit"
            block["error_message"] = str(exc)[:200]
            return block
        block["predicted"] = [{**p["after"], "confidence": None, "source_decision": p["evidence"]}
                              for p in plan["proposals"] if p["kind"] == "create"]
        block["questions"] = plan["questions"]
        block["steps"] = plan["steps"]
        block["model"] = plan["model"]
        return block
    return block


def parse_runs(set_name: str, runs: int) -> None:
    transcript_dir, annotations_path, _ = TEST_SETS[set_name]
    annotations = json.loads(annotations_path.read_text())
    cache_path = AGENT_CACHES[set_name]
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {
        "note": "Meeting-agent predictions on an empty board; see eval/agent_eval.py.", "runs": []}
    for i in range(runs):
        print(f"--- agent run {i + 1}/{runs} on the {set_name} set ---", flush=True)
        with ThreadPoolExecutor(WORKERS) as pool:
            blocks = list(pool.map(lambda e: review_one(transcript_dir, e), annotations))
        for b in blocks:
            note = f"  [{b['error'].upper()}: {b.get('error_message', '')[:60]}]" if b.get("error") else ""
            print(f"  {b['transcript_file']:32} {len(b['predicted'])} tasks, "
                  f"{len(b['questions'])} questions{note}", flush=True)
        cache["runs"].append({
            "conditions": {"agent": blocks},
            "models": {"agent": next((b["model"] for b in blocks if b.get("model")), None)},
            "validation_failures": {"agent": sum(b.get("error") == "limit" for b in blocks)},
            "api_failures": {"agent": sum(b.get("error") == "api" for b in blocks)},
        })
        # Saved after every run, so an interrupted batch keeps what it already paid for.
        cache_path.write_text(json.dumps(cache, indent=1))


def score_set(set_name: str) -> dict | None:
    _, annotations_path, parser_cache_path = TEST_SETS[set_name]
    if not AGENT_CACHES[set_name].exists():
        return None
    annotations = json.loads(annotations_path.read_text())
    agent_runs = json.loads(AGENT_CACHES[set_name].read_text())["runs"]
    parser_runs = runs_with(json.loads(parser_cache_path.read_text()), PARSER)
    # The matcher is "overlap", as for every reported parser figure.
    scored = {"agent": [score_condition(r["conditions"]["agent"], annotations, "overlap") for r in agent_runs],
              PARSER: [score_condition(r["conditions"][PARSER], annotations, "overlap") for r in parser_runs]}
    out = {"runs": {k: len(v) for k, v in scored.items()}, "means": {}, "tests": {}}
    for name, per_run in scored.items():
        out["means"][name] = {}
        for m in METRICS:
            vals = [r[m] for r in per_run if r[m] is not None]
            out["means"][name][m] = round(stats.mean(vals), 3) if vals else None
        out["means"][name]["items_per_run"] = round(stats.mean(r["predicted_items"] for r in per_run), 1)
    out["tests"] = {m: permutation_test([r[m] for r in scored["agent"]], [r[m] for r in scored[PARSER]])
                    for m in ("precision", "recall", "f1")}
    blocks = [b for r in agent_runs for b in r["conditions"]["agent"]]
    out["agent"] = {
        "reviews": len(blocks),
        "failed_reviews": sum(b.get("error") == "limit" for b in blocks),
        "api_failures": sum(b.get("error") == "api" for b in blocks),
        "questions_per_review": round(stats.mean(len(b["questions"]) for b in blocks), 2),
        "mean_steps": round(stats.mean(b["steps"] for b in blocks if "steps" in b), 2)
        if any("steps" in b for b in blocks) else None,
        "model": next((r["models"]["agent"] for r in agent_runs if r["models"].get("agent")), None),
        "expected_items": scored["agent"][0]["expected_items"] if scored["agent"] else None,
    }
    return out


def pct(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def render(results: dict, reconciliation: dict | None = None) -> str:
    lines = [
        "# Meeting-agent evaluation",
        "",
        "Generated by `python -m eval.agent_eval --write-report` from saved runs, so no model is called.",
        "Part 1 tested whether the agent should extract a meeting's tasks; the result decided its role.",
        "Part 2 measures that role: reconciling a follow-up meeting with the board.",
        "",
        "## Part 1. Should the agent extract a meeting's tasks, or the parser?",
        "",
        "From the cached predictions in `eval/agent_predictions*.json`. The agent imports each test",
        "meeting onto an empty board, so",
        "every task it proposes is a new task, the same job the parser does. Its tasks are scored with",
        "the parser evaluation's overlap matcher and answer keys, against the implemented parser",
        f"configuration (`{PARSER}`, Gemini Flash with guidance) from the parser's own caches.",
        "Questions the agent asks instead of adding a task count as missed items, as in the app.",
        "",
    ]
    for set_name, r in results.items():
        if r is None:
            continue
        a, p = r["means"]["agent"], r["means"][PARSER]
        lines += [f"### {set_name.title()} set ({r['agent']['expected_items']} annotated tasks per run)", "",
                  f"| | Meeting agent ({r['runs']['agent']} runs) | Parser ({r['runs'][PARSER]} runs) | Difference | p |",
                  "|---|---|---|---|---|"]
        for m in ("precision", "recall", "f1"):
            diff, pval = r["tests"][m]
            lines.append(f"| {m.title() if m != 'f1' else 'F1'} | {pct(a[m])} | {pct(p[m])} | {diff:+.3f} | {pval} |")
        for m, label in (("owner_accuracy", "Owner accuracy"), ("status_accuracy", "Status accuracy"),
                         ("deadline_exact_accuracy", "Deadline exact"),
                         (f"deadline_within_{DEADLINE_TOLERANCE_DAYS}d_accuracy",
                          f"Deadline within {DEADLINE_TOLERANCE_DAYS} days")):
            lines.append(f"| {label} | {pct(a[m])} | {pct(p[m])} | | |")
        lines.append(f"| Tasks per run | {a['items_per_run']} | {p['items_per_run']} | | |")
        ag = r["agent"]
        lines += ["", f"Agent reviews: {ag['reviews']}; not completed within limits: {ag['failed_reviews']}; "
                      f"provider errors excluded: {ag['api_failures']}; questions per review: "
                      f"{ag['questions_per_review']}; model calls per review: {ag['mean_steps']} (measured when "
                      "the agent fetched the board with its own call; it is now sent with the request). "
                      f"Model: {ag['model']}.", ""]
    lines += [
        "### What this decided",
        "",
        "The agent's tasks were at least as precise as the parser's, but it found significantly fewer of",
        "them on the long set, and on an empty board it sometimes proposed none at all, asking for the",
        "board to be filled first. The app therefore keeps the parser for extraction: every meeting's tasks",
        "come from the parser, with their confidence scores, and the agent is not called on an empty board.",
        "On a board that already has tasks, the agent receives the parser's tasks as candidates, marks those",
        "already on the board so they are not added twice, and proposes changes to existing tasks for the",
        "user to approve. That reconciliation step is scored in Part 2.",
        "",
        "### Reading Part 1",
        "",
        "p is an exact two-sided permutation test over the per-run values, as in the parser",
        "evaluation. The parser's figures are the published ones; only the agent was run for this",
        "report. The same limits apply as to the parser evaluation: eight synthetic meetings, one",
        "annotator, and a long set drafted with an assistant from the Claude family.",
        "",
    ]
    if reconciliation is not None:
        lines += render_section(reconciliation)
    return "\n".join(lines)


def write_report() -> None:
    """Rewrite docs/agent-evaluation.md from both saved runs (free)."""
    results = {s: score_set(s) for s in ("short", "long")}
    reconciliation = score(json.loads(PREDICTIONS.read_text())) if PREDICTIONS.exists() else None
    REPORT_MD.write_text(render(results, reconciliation))
    print(f"wrote {REPORT_MD.relative_to(REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--parse", action="store_true", help="run the agent (calls Gemini)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--set", dest="test_set", choices=["short", "long", "both"], default="both")
    ap.add_argument("--write-report", action="store_true")
    args = ap.parse_args()
    sets = ["short", "long"] if args.test_set == "both" else [args.test_set]
    if args.parse:
        for s in sets:
            parse_runs(s, args.runs)
    results = {s: score_set(s) for s in ("short", "long")}
    RESULTS_JSON.write_text(json.dumps(results, indent=1))
    for s, r in results.items():
        if r:
            print(f"{s}: agent F1 {pct(r['means']['agent']['f1'])} vs parser {pct(r['means'][PARSER]['f1'])}"
                  f" (diff {r['tests']['f1'][0]:+.3f}, p={r['tests']['f1'][1]})")
    if args.write_report:
        write_report()


if __name__ == "__main__":
    main()
