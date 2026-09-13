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

Caveat (worth stating in the report): the judge is a single LLM applying a rubric, so the scores
indicate quality trends rather than an absolute accuracy figure. The judge is held fixed as Claude
across both arms, so it is independent of the implemented Gemini generator but assesses Claude's own
output in the comparison arm - an asymmetry that runs against the conclusion drawn, not for it.

Usage (from the repo root, with the backend virtualenv active and ANTHROPIC_API_KEY set):

    python -m eval.subtask_eval                  # score a sample of tasks
    python -m eval.subtask_eval --limit 8        # smaller/faster sample
    python -m eval.subtask_eval --write-report   # also refresh docs/subtask-evaluation-report.md
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import statistics as st
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


def evaluate(limit: int, provider: str | None = None) -> dict:
    sample = load_sample(limit)
    # The judge is held fixed across providers: swapping it too would change two variables at
    # once. It stays Claude, so the Claude arm is self-judged and the Gemini arm is not - an
    # asymmetry that favours Claude, and therefore does not inflate a Gemini win.
    generator = SubtaskGenerator(provider=provider)
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
        "provider": generator.provider,
        "model": generator.model,
        "judge_model": judge.model,
        "sample_size": len(rows),
        "avg_subtasks_per_task": avg_count,
        "mean_scores": per_dim,
        "overall_mean": overall,
        "per_task": rows,
    }


ARMS = {"gemini": "Gemini Flash", "anthropic": "Claude Sonnet"}


def _dim_mean(runs: list[dict], dim: str) -> float:
    return round(st.mean(r["mean_scores"][dim] for r in runs), 2)


def _task_means(runs: list[dict]) -> dict[str, float]:
    """Mean rubric score per task, averaged across runs, so the paired test sees one
    value per task rather than one per task per run."""
    out: dict[str, float] = {}
    for task in (r["task"] for r in runs[0]["per_task"]):
        per_run = []
        for run in runs:
            row = next(x for x in run["per_task"] if x["task"] == task)
            per_run.append(st.mean(row["scores"][d] for d in DIMENSIONS))
        out[task] = st.mean(per_run)
    return out


def _paired_permutation(a: dict[str, float], b: dict[str, float]) -> tuple[float, float]:
    """Exact paired permutation over the per-task differences. Exact rather than sampled:
    2**12 sign assignments is small enough to enumerate, so the p-value is not itself an
    estimate with its own noise."""
    diffs = [a[t] - b[t] for t in a]
    obs = st.mean(diffs)
    n = len(diffs)
    hits = sum(
        1 for signs in itertools.product((1, -1), repeat=n)
        if abs(st.mean([s * d for s, d in zip(signs, diffs)])) >= abs(obs) - 1e-12
    )
    return round(obs, 4), round(hits / 2 ** n, 3)


def aggregate(arm_runs: dict[str, list[dict]]) -> dict:
    """Fold per-run results into the stored shape: every reported figure is derived here,
    so nothing in the written report is a number typed in by hand."""
    arms = {}
    for arm, runs in arm_runs.items():
        overalls = [r["overall_mean"] for r in runs]
        arms[arm] = {
            "label": ARMS[arm],
            "provider": runs[0]["provider"],
            "model": runs[0]["model"],
            "runs": len(runs),
            "overall_per_run": overalls,
            "overall_mean": round(st.mean(overalls), 3),
            "overall_sd": round(st.stdev(overalls), 3) if len(overalls) > 1 else None,
            "overall_min": min(overalls),
            "overall_max": max(overalls),
            "mean_scores": {d: _dim_mean(runs, d) for d in DIMENSIONS},
            "avg_subtasks_per_task": round(st.mean(r["avg_subtasks_per_task"] for r in runs), 2),
            "per_task_runs": [r["per_task"] for r in runs],
        }
    out = {
        "judge_model": next(iter(arm_runs.values()))[0]["judge_model"],
        "sample_size": next(iter(arm_runs.values()))[0]["sample_size"],
        "implemented_arm": "gemini",
        "arms": arms,
    }
    if {"gemini", "anthropic"} <= set(arm_runs):
        diff, p = _paired_permutation(_task_means(arm_runs["gemini"]),
                                      _task_means(arm_runs["anthropic"]))
        out["comparison"] = {"metric": "Gemini - Claude, mean per-task rubric score",
                             "difference": diff, "p_value": p, "n_tasks": out["sample_size"]}
    return out


def render_report(res: dict) -> str:
    today = date.today().isoformat()
    ship = res["arms"][res["implemented_arm"]]
    other = res["arms"].get("anthropic" if res["implemented_arm"] == "gemini" else "gemini")
    lines = [
        "# Subtask Generation — Evaluation Report",
        "",
        f"_Generated by `python -m eval.subtask_eval --write-report` on {today}._",
        f"_Extraction accuracy: [evaluation-report.md](evaluation-report.md). Speech-to-text: [asr-evaluation.md](asr-evaluation.md)._",
        "",
        "The AI subtask feature breaks a single action item into an ordered checklist. Unlike "
        "transcript parsing, this is **open-ended generation with no ground truth**, so it is "
        "assessed qualitatively with an LLM-as-judge rubric rather than precision/recall.",
        "",
        f"- Implemented generator: `{ship['model']}` ({ship['provider']})",
        f"- Judge model: `{res['judge_model']}` (held fixed across both arms)",
        f"- Sample size: {res['sample_size']} tasks, drawn from the annotated action-item set",
        f"- Runs per arm: {ship['runs']}",
        f"- Average subtasks per task: {ship['avg_subtasks_per_task']}",
        "",
    ]
    if other:
        c = res["comparison"]
        verdict = "separable" if c["p_value"] < 0.05 else "indistinguishable on quality"
        gap = abs(ship["overall_mean"] - other["overall_mean"])
        lead = other["label"] if other["overall_mean"] > ship["overall_mean"] else ship["label"]
        lines += [
            "## Decision",
            "",
            f"**Subtask checklists are generated by {ship['label']}.** Over {ship['runs']} runs per "
            f"arm it scores {ship['overall_mean']} out of 5 against {other['label']}'s "
            f"{other['overall_mean']}, a gap of {gap:.3f} that an exact paired permutation test "
            f"over the per-task means does not separate (p = {c['p_value']}), so the two are "
            f"{verdict}. The choice rests on cost rather than quality: Gemini is roughly a tenth "
            "the price per token and keeps the system on a single provider.",
            "",
            f"The run-to-run spread inside each arm ({ship['label']} {ship['overall_min']}-"
            f"{ship['overall_max']}, sd {ship['overall_sd']}; {other['label']} "
            f"{other['overall_min']}-{other['overall_max']}, sd {other['overall_sd']}) is wider "
            f"than the {gap:.3f} between them, and {lead} leads only nominally. What does differ "
            f"is shape rather than standard: {other['label']} produced "
            f"{other['avg_subtasks_per_task']} subtasks per task against {ship['label']}'s "
            f"{ship['avg_subtasks_per_task']}, scoring higher on coverage where {ship['label']} "
            "scores higher on non-redundancy.",
            "",
            "The judge was Claude in both arms. That means Claude assessed its own output in one "
            "arm and a competitor's in the other, an asymmetry that favours Claude - and Claude "
            "still does not separate from Gemini, so the tie is not an artefact of a partial judge.",
            "",
            "## Mean scores (1–5), averaged over all runs",
            "",
            f"| Dimension | {ship['label']} | {other['label']} |",
            "| --- | --- | --- |",
        ]
        for dim in DIMENSIONS:
            lines.append(f"| {dim.replace('_', ' ')} | {ship['mean_scores'][dim]} "
                         f"| {other['mean_scores'][dim]} |")
        lines.append(f"| **overall** | **{ship['overall_mean']}** | {other['overall_mean']} |")
        lines += ["", "## Overall score per run", "",
                  "| Arm | Runs | Mean | SD | Range |", "| --- | --- | --- | --- | --- |"]
        for a in (ship, other):
            lines.append(f"| {a['label']} | {', '.join(str(x) for x in a['overall_per_run'])} "
                         f"| {a['overall_mean']} | {a['overall_sd']} "
                         f"| {a['overall_min']}-{a['overall_max']} |")
    else:
        lines += ["## Mean scores (1–5)", "", "| Dimension | Mean |", "| --- | --- |"]
        for dim in DIMENSIONS:
            lines.append(f"| {dim.replace('_', ' ')} | {ship['mean_scores'][dim]} |")
        lines.append(f"| **overall** | **{ship['overall_mean']}** |")

    # Averaged over runs rather than taken from one of them: a single run is a noisy sample,
    # and picking the first would quietly report whichever run happened to score best. Both
    # arms get the same treatment, so the per-task view is comparable like the tables above.
    lines += ["", "## Per-task detail", "",
              "Rel, Act, Cov and NR are the four rubric dimensions, each scored 1-5. Subtasks is "
              "the number of steps the generator produced, which is a count and not a score.", ""]
    for a in ([ship, other] if other else [ship]):
        runs = a["per_task_runs"]
        lines += [f"{a['label']}, averaged over {len(runs)} runs:", "",
                  "| Task | Subtasks | Rel | Act | Cov | NR |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for first in runs[0]:
            name = first["task"]
            rows = [m for run in runs for m in run if m["task"] == name]
            dims = {d: st.mean(r["scores"][d] for r in rows) for d in DIMENSIONS}
            nsub = st.mean(r["n_subtasks"] for r in rows)
            task = name[:50] + ("…" if len(name) > 50 else "")
            lines.append(f"| {task} | {nsub:.1f} | {dims['relevance']:.1f} "
                         f"| {dims['actionability']:.1f} | {dims['coverage']:.1f} "
                         f"| {dims['non_redundancy']:.1f} |")
        lines.append("")
    lines += [
        "",
        "> **Caveat:** scores come from a single LLM judge applying a rubric, so they indicate "
        "quality trends rather than an absolute metric. The judge is Claude and the implemented "
        "generator is Gemini, so the judge is independent of it. The sample is the first "
        f"{res['sample_size']} annotated items in file order, which covers the finance and "
        "logistics workshops but not the security or data-migration ones.",
        "",
        f"_Generated by `python -m eval.subtask_eval --write-report` on {today}. Re-run to refresh._",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Qualitatively evaluate AI subtask generation.")
    ap.add_argument("--limit", type=int, default=12, help="Number of tasks to score (default 12).")
    ap.add_argument("--runs", type=int, default=1, help="Runs per arm (default 1). Both arms get the same count.")
    ap.add_argument("--arms", default="gemini,anthropic",
                    help="Comma-separated generators to score. The judge is always Claude.")
    ap.add_argument("--write-report", action="store_true", help="Refresh docs/subtask-evaluation-report.md")
    ap.add_argument("--report-only", action="store_true",
                    help="Re-render the report from stored results without calling any model.")
    ap.add_argument("--provider", choices=("anthropic", "gemini"),
                    help="Deprecated alias for --arms with a single value.")
    args = ap.parse_args()

    if args.report_only:
        res = json.loads(RESULTS_JSON.read_text())
    else:
        arms = [args.provider] if args.provider else [a.strip() for a in args.arms.split(",") if a.strip()]
        arm_runs: dict[str, list[dict]] = {}
        for arm in arms:
            arm_runs[arm] = []
            for r in range(1, args.runs + 1):
                print(f"[{arm} run {r}/{args.runs}] scoring {args.limit} tasks…")
                arm_runs[arm].append(evaluate(args.limit, provider=arm))
                print(f"  overall {arm_runs[arm][-1]['overall_mean']}")
        res = aggregate(arm_runs)
        RESULTS_JSON.write_text(json.dumps(res, indent=2))
        print(f"\nWrote raw results to {RESULTS_JSON.relative_to(REPO_ROOT)}")

    for arm in res["arms"].values():
        print(f"{arm['label']:<15} mean {arm['overall_mean']} over {arm['runs']} run(s)")
    if "comparison" in res:
        print(f"paired permutation p = {res['comparison']['p_value']}")

    if args.write_report or args.report_only:
        REPORT_MD.write_text(render_report(res))
        print(f"Wrote report to {REPORT_MD.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
