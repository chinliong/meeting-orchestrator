"""Qualitative evaluation of the AI subtask-generation feature.

Unlike transcript parsing (see eval/run_eval.py), subtask generation is *open-ended*: there is
no single correct way to break a task down, so there is no ground truth to score precision/
recall against. Instead this harness measures quality with an LLM-as-judge rubric — each
generated breakdown is scored 1-5 on four dimensions:

  - relevance       — do the subtasks actually belong to this task?
  - actionability   — is each a concrete, doable step (not vague or restating the task)?
  - coverage        — together, do they plausibly complete the task end to end?
  - non_redundancy  — are they distinct, without duplicate or overlapping steps?

The sample is drawn from the same annotated action items used for the transcript evaluation, so
the tasks are realistic enterprise-programme work. The judge model is prompted independently of
the generator and returns structured scores via tool-use.

Caveat (worth stating in the report): generator and judge are both Claude, so the judge is not a
fully independent assessor. The scores indicate quality trends, not an absolute accuracy figure.

Usage (from the repo root, with the backend virtualenv active and ANTHROPIC_API_KEY set):

    python -m eval.subtask_eval                  # score a sample of tasks
    python -m eval.subtask_eval --limit 8        # smaller/faster sample
    python -m eval.subtask_eval --write-report   # also refresh docs/subtask-evaluation-report.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
ANNOTATIONS = REPO_ROOT / "data" / "annotated-test-set" / "annotations.json"
RESULTS_JSON = REPO_ROOT / "eval" / "subtask_results.json"
REPORT_MD = REPO_ROOT / "docs" / "subtask-evaluation-report.md"

# Make the backend `app` package importable and load ANTHROPIC_API_KEY from backend/.env.
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

import anthropic  # noqa: E402

from app.llm.subtasks import SubtaskGenerator  # noqa: E402

DIMENSIONS = ["relevance", "actionability", "coverage", "non_redundancy"]

JUDGE_TOOL = {
    "name": "score_subtasks",
    "description": "Record the rubric scores for a generated subtask breakdown.",
    "input_schema": {
        "type": "object",
        "properties": {
            **{
                dim: {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": f"Score for {dim} (1 = poor, 5 = excellent).",
                }
                for dim in DIMENSIONS
            },
            "comment": {
                "type": "string",
                "description": "One short sentence justifying the scores.",
            },
        },
        "required": [*DIMENSIONS, "comment"],
    },
}

JUDGE_SYSTEM = """You are a strict evaluator of AI-generated task breakdowns for enterprise \
project management. Given a parent task and the subtasks generated for it, score the breakdown \
1-5 on each rubric dimension:

- relevance: do the subtasks genuinely belong to this task?
- actionability: is each subtask a concrete, doable step (not vague, and not just restating the task)?
- coverage: taken together, would completing them plausibly complete the task end to end?
- non_redundancy: are the subtasks distinct, with no duplicate or heavily overlapping steps?

Be discerning — reserve 5 for genuinely strong breakdowns. Always respond by calling the \
score_subtasks tool."""


def load_sample(limit: int) -> list[dict]:
    """Flatten the annotated action items into standalone tasks for breakdown."""
    data = json.loads(ANNOTATIONS.read_text())
    tasks: list[dict] = []
    for meeting in data:
        decision = (meeting.get("expected_decisions") or [None])[0]
        title = Path(meeting["transcript_file"]).stem.replace("-", " ").title()
        for item in meeting.get("expected_action_items", []):
            tasks.append(
                {
                    "description": item["description"],
                    "owner": item.get("owner"),
                    "deadline": item.get("deadline"),
                    "source_decision": decision,
                    "meeting_title": title,
                }
            )
    return tasks[:limit]


def _as_task(spec: dict) -> SimpleNamespace:
    """A lightweight stand-in carrying only the attributes SubtaskGenerator reads — avoids
    needing a database session just to generate."""
    deadline = date.fromisoformat(spec["deadline"]) if spec.get("deadline") else None
    return SimpleNamespace(
        description=spec["description"],
        owner=spec.get("owner"),
        deadline=deadline,
        source_decision=spec.get("source_decision"),
        meeting_title=spec.get("meeting_title"),
        project=SimpleNamespace(name="SAP S/4HANA Go-Live Programme"),
        subtasks=[],
    )


class SubtaskJudge:
    def __init__(self, model: str | None = None):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = model or os.getenv("JUDGE_MODEL", os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"))

    def score(self, task_desc: str, subtasks: list[str]) -> dict:
        rendered = "\n".join(f"- {s}" for s in subtasks)
        message = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=JUDGE_SYSTEM,
            tools=[JUDGE_TOOL],
            tool_choice={"type": "tool", "name": "score_subtasks"},
            messages=[
                {
                    "role": "user",
                    "content": f"Parent task: {task_desc}\n\nGenerated subtasks:\n{rendered}",
                }
            ],
        )
        tool_use = next(b for b in message.content if b.type == "tool_use")
        return tool_use.input


def evaluate(limit: int) -> dict:
    sample = load_sample(limit)
    generator = SubtaskGenerator()
    judge = SubtaskJudge()

    rows: list[dict] = []
    for i, spec in enumerate(sample, 1):
        print(f"  [{i}/{len(sample)}] {spec['description'][:60]}…")
        subtasks = generator.generate(_as_task(spec))
        scores = judge.score(spec["description"], subtasks)
        rows.append(
            {
                "task": spec["description"],
                "subtasks": subtasks,
                "n_subtasks": len(subtasks),
                "scores": {dim: scores[dim] for dim in DIMENSIONS},
                "comment": scores.get("comment", ""),
            }
        )

    # Aggregate: mean per dimension, plus an overall mean across all dimensions.
    n = len(rows) or 1
    per_dim = {dim: round(sum(r["scores"][dim] for r in rows) / n, 2) for dim in DIMENSIONS}
    overall = round(sum(per_dim.values()) / len(DIMENSIONS), 2)
    avg_count = round(sum(r["n_subtasks"] for r in rows) / n, 1)

    return {
        "model": generator.model,
        "judge_model": judge.model,
        "sample_size": len(rows),
        "avg_subtasks_per_task": avg_count,
        "mean_scores": per_dim,
        "overall_mean": overall,
        "per_task": rows,
    }


def render_report(result: dict) -> str:
    today = date.today().isoformat()
    lines = [
        "# Subtask Generation — Evaluation Report",
        "",
        "The AI subtask feature breaks a single action item into an ordered checklist. Unlike "
        "transcript parsing, this is **open-ended generation with no ground truth**, so it is "
        "assessed qualitatively with an LLM-as-judge rubric rather than precision/recall.",
        "",
        f"- Generator model: `{result['model']}`",
        f"- Judge model: `{result['judge_model']}`",
        f"- Sample size: {result['sample_size']} tasks (drawn from the annotated action-item set)",
        f"- Average subtasks per task: {result['avg_subtasks_per_task']}",
        "",
        "## Mean scores (1–5)",
        "",
        "| Dimension | Mean |",
        "| --- | --- |",
    ]
    for dim in DIMENSIONS:
        lines.append(f"| {dim.replace('_', ' ')} | {result['mean_scores'][dim]} |")
    lines.append(f"| **overall** | **{result['overall_mean']}** |")
    lines += [
        "",
        "## Per-task detail",
        "",
        "| Task | # | Rel | Act | Cov | NR |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in result["per_task"]:
        s = r["scores"]
        task = r["task"][:50] + ("…" if len(r["task"]) > 50 else "")
        lines.append(
            f"| {task} | {r['n_subtasks']} | {s['relevance']} | {s['actionability']} "
            f"| {s['coverage']} | {s['non_redundancy']} |"
        )
    lines += [
        "",
        "> **Caveat:** the generator and judge are both Claude, so the judge is not a fully "
        "independent assessor. These scores indicate quality trends, not an absolute metric.",
        "",
        f"_Generated by `python -m eval.subtask_eval --write-report` on {today}. Re-run to refresh._",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Qualitatively evaluate AI subtask generation.")
    ap.add_argument("--limit", type=int, default=12, help="Number of tasks to score (default 12).")
    ap.add_argument("--write-report", action="store_true", help="Refresh docs/subtask-evaluation-report.md")
    args = ap.parse_args()

    print(f"Evaluating subtask generation on {args.limit} tasks…")
    result = evaluate(args.limit)

    print("\n=== Mean scores (1-5) ===")
    print(json.dumps({**result["mean_scores"], "overall": result["overall_mean"]}, indent=2))

    RESULTS_JSON.write_text(json.dumps(result, indent=2))
    print(f"\nWrote raw results to {RESULTS_JSON.relative_to(REPO_ROOT)}")

    if args.write_report:
        REPORT_MD.write_text(render_report(result))
        print(f"Wrote report to {REPORT_MD.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
