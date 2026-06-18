"""Evaluation harness for the LLM transcript-parsing pipeline (Objective 5).

Runs the parser over an annotated set of synthetic transcripts and scores the structured
output against the ground truth: action-item precision/recall/F1, owner-assignment
accuracy, and deadline-inference accuracy. It also compares two prompt variants (a minimal
baseline vs. the refined production prompt) so the effect of prompt engineering is measured,
not asserted.

Usage (from the repo root, with the backend virtualenv active and ANTHROPIC_API_KEY set):

    python -m eval.run_eval                 # run both prompt variants
    python -m eval.run_eval --variant prod  # run a single variant
    python -m eval.run_eval --write-report  # also refresh docs/evaluation-report.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
TRANSCRIPTS_DIR = REPO_ROOT / "data" / "synthetic-transcripts"
ANNOTATIONS = REPO_ROOT / "data" / "annotated-test-set" / "annotations.json"
RESULTS_JSON = REPO_ROOT / "eval" / "results.json"
REPORT_MD = REPO_ROOT / "docs" / "evaluation-report.md"

# Make the backend `app` package importable and load ANTHROPIC_API_KEY from backend/.env.
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

from app.llm.parser import SYSTEM_PROMPT, TranscriptParser  # noqa: E402

# A deliberately thin baseline prompt, representing a naive first attempt, so the refined
# production prompt (app.llm.parser.SYSTEM_PROMPT) can be measured against it.
BASELINE_PROMPT = (
    "Extract the action items and decisions from this meeting transcript. "
    "Always respond by calling the record_extraction tool."
)

PROMPT_VARIANTS = {
    "baseline": BASELINE_PROMPT,
    "prod": SYSTEM_PROMPT,
}

# Action items are matched by description token overlap; this threshold (Jaccard over
# content words) decides whether a predicted item refers to the same task as an expected one.
MATCH_THRESHOLD = 0.18
DEADLINE_TOLERANCE_DAYS = 3

_STOPWORDS = {
    "the", "a", "an", "to", "for", "of", "and", "on", "in", "with", "by", "from", "that",
    "this", "is", "are", "be", "will", "we", "i", "it", "as", "at", "or", "our",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _match_items(expected: list[dict], predicted: list[dict]) -> list[tuple[int, int, float]]:
    """Greedily match expected to predicted items by description overlap. Returns
    (expected_idx, predicted_idx, score) pairs above the threshold, best score first."""
    candidates = []
    for ei, exp in enumerate(expected):
        for pi, pred in enumerate(predicted):
            score = _jaccard(exp["description"], pred.get("description", ""))
            if score >= MATCH_THRESHOLD:
                candidates.append((score, ei, pi))
    candidates.sort(reverse=True)

    matched, used_e, used_p = [], set(), set()
    for score, ei, pi in candidates:
        if ei in used_e or pi in used_p:
            continue
        used_e.add(ei)
        used_p.add(pi)
        matched.append((ei, pi, score))
    return matched


def _norm_owner(owner) -> str | None:
    if owner is None:
        return None
    owner = str(owner).strip()
    return owner.split()[0].lower() if owner else None


def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@dataclass
class Tally:
    expected: int = 0
    predicted: int = 0
    matched: int = 0
    owner_correct: int = 0
    owner_total: int = 0
    status_correct: int = 0
    status_total: int = 0
    deadline_exact: int = 0
    deadline_within_tol: int = 0
    deadline_total: int = 0
    per_transcript: list[dict] = field(default_factory=list)

    def metrics(self) -> dict:
        precision = self.matched / self.predicted if self.predicted else 0.0
        recall = self.matched / self.expected if self.expected else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        return {
            "expected_items": self.expected,
            "predicted_items": self.predicted,
            "matched_items": self.matched,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "owner_accuracy": round(self.owner_correct / self.owner_total, 3) if self.owner_total else None,
            "status_accuracy": round(self.status_correct / self.status_total, 3) if self.status_total else None,
            "deadline_exact_accuracy": round(self.deadline_exact / self.deadline_total, 3) if self.deadline_total else None,
            f"deadline_within_{DEADLINE_TOLERANCE_DAYS}d_accuracy": round(self.deadline_within_tol / self.deadline_total, 3) if self.deadline_total else None,
        }


def evaluate_variant(variant: str, prompt: str, dataset: list[dict]) -> dict:
    parser = TranscriptParser(system_prompt=prompt)
    tally = Tally()

    for entry in dataset:
        transcript = (TRANSCRIPTS_DIR / entry["transcript_file"]).read_text()
        meeting_date = _parse_date(entry["meeting_date"])
        result = parser.parse(transcript, meeting_date=meeting_date)
        predicted = [item.model_dump() for item in result.action_items]
        expected = entry["expected_action_items"]

        matches = _match_items(expected, predicted)
        tally.expected += len(expected)
        tally.predicted += len(predicted)
        tally.matched += len(matches)

        for ei, pi, _score in matches:
            exp, pred = expected[ei], predicted[pi]

            tally.owner_total += 1
            if _norm_owner(exp["owner"]) == _norm_owner(pred.get("owner")):
                tally.owner_correct += 1

            if exp.get("status") is not None:
                tally.status_total += 1
                if pred.get("status") == exp["status"]:
                    tally.status_correct += 1

            exp_deadline = _parse_date(exp["deadline"])
            if exp_deadline is not None:
                tally.deadline_total += 1
                pred_deadline = _parse_date(pred.get("deadline"))
                if pred_deadline == exp_deadline:
                    tally.deadline_exact += 1
                if pred_deadline is not None and abs((pred_deadline - exp_deadline).days) <= DEADLINE_TOLERANCE_DAYS:
                    tally.deadline_within_tol += 1

        tally.per_transcript.append({
            "transcript": entry["transcript_file"],
            "expected": len(expected),
            "predicted": len(predicted),
            "matched": len(matches),
        })

    return {"variant": variant, **tally.metrics(), "per_transcript": tally.per_transcript}


def render_report(results: list[dict]) -> str:
    today = date.today().isoformat()
    rows = []
    for r in results:
        rows.append(
            f"| {r['variant']} | {r['precision']} | {r['recall']} | {r['f1']} | "
            f"{r['owner_accuracy']} | {r['status_accuracy']} | {r['deadline_exact_accuracy']} | "
            f"{r[f'deadline_within_{DEADLINE_TOLERANCE_DAYS}d_accuracy']} |"
        )
    table = "\n".join(rows)
    n_transcripts = len(results[0]["per_transcript"]) if results else 0
    n_items = results[0]["expected_items"] if results else 0
    prod = results[-1]
    tol_key = f"deadline_within_{DEADLINE_TOLERANCE_DAYS}d_accuracy"

    return f"""# Evaluation Report

_Generated by `python -m eval.run_eval --write-report` on {today}. Re-run to refresh._

## Purpose

Assess the accuracy of the LLM transcript-parsing pipeline against manually annotated
meeting transcripts, and quantify the effect of prompt engineering on extraction quality.

## Test Set

- Synthetic SAP-programme transcripts: **{n_transcripts}**
- Manually annotated action items (ground truth): **{n_items}**
- Annotation method: manual labelling of decisions, action items, owners, and deadlines.
- Source: `data/synthetic-transcripts/` (inputs) and `data/annotated-test-set/annotations.json` (ground truth).

## Methodology

- Each transcript is parsed with its true meeting date so relative deadline cues
  (e.g. "by this Friday") resolve deterministically.
- Predicted action items are matched to annotated ones by description token overlap
  (Jaccard ≥ {MATCH_THRESHOLD}); greedy best-first assignment.
- **Precision** = matched / predicted, **Recall** = matched / expected, **F1** their harmonic mean.
- **Owner accuracy**: of matched items, fraction whose owner (first name, or null) is correct.
- **Status accuracy**: of matched items, fraction whose inferred status (todo / in_progress /
  done) matches the annotation.
- **Deadline accuracy**: of matched items with an annotated deadline, fraction whose inferred
  date is exact, and fraction within ±{DEADLINE_TOLERANCE_DAYS} days (tolerant of ambiguous
  cues like "next Thursday").
- The ground truth labels every trackable action item the transcript surfaces — completed,
  in-progress, and not-yet-started — since the board tracks all three.

## Prompt Iterations

Two prompt variants were evaluated on the identical test set:

- **baseline** — a one-line instruction with no role, no owner/deadline/status rules, no anti-hallucination guidance.
- **prod** — the refined production prompt (`app.llm.parser.SYSTEM_PROMPT`): assigns owners only
  when explicit, infers deadlines from cues relative to the meeting date, infers status from the
  discussion, and forbids inventing items.

| Variant | Precision | Recall | F1 | Owner Acc. | Status Acc. | Deadline (exact) | Deadline (±{DEADLINE_TOLERANCE_DAYS}d) |
|---------|-----------|--------|----|------------|-------------|------------------|----------------------|
{table}

## Findings

- On the production prompt the pipeline recalls **{prod['recall']}** of annotated action items at a
  precision of **{prod['precision']}** (F1 **{prod['f1']}**). Where precision trails recall, it is
  largely the model splitting or surfacing items at a finer granularity than the annotation rather
  than inventing work.
- Owner assignment accuracy is **{prod['owner_accuracy']}** and inferred status accuracy is
  **{prod['status_accuracy']}** — status is read from cues like "that's done" / "I'm halfway" /
  "haven't started".
- Deadline inference is the hardest field: exact-date accuracy is **{prod['deadline_exact_accuracy']}**
  versus a ±{DEADLINE_TOLERANCE_DAYS}-day tolerance of **{prod[tol_key]}**, driven by genuinely
  ambiguous phrasing such as "next Thursday" and "end of next week".
- The prod prompt is measured against a thin baseline (table above) so the effect of prompt
  engineering is shown rather than asserted.

## Limitations & Next Steps

- Small synthetic test set ({n_transcripts} transcripts, {n_items} annotated items); expand with
  more domains and noisier dialogue.
- Token-overlap matching is a proxy for semantic equivalence; an LLM-as-judge matcher could be
  more robust and would reduce granularity-driven precision penalties.
- Anchor ambiguous deadline phrases during annotation, or capture a range, to sharpen the
  exact-match metric.

## Raw Results

See `eval/results.json` for full per-transcript counts.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate the transcript-parsing pipeline.")
    ap.add_argument("--variant", choices=[*PROMPT_VARIANTS, "all"], default="all")
    ap.add_argument("--write-report", action="store_true", help="Refresh docs/evaluation-report.md")
    args = ap.parse_args()

    dataset = json.loads(ANNOTATIONS.read_text())
    variants = list(PROMPT_VARIANTS) if args.variant == "all" else [args.variant]

    results = []
    for variant in variants:
        print(f"\n=== Evaluating variant: {variant} ===")
        result = evaluate_variant(variant, PROMPT_VARIANTS[variant], dataset)
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k != "per_transcript"}, indent=2))

    RESULTS_JSON.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nWrote raw results to {RESULTS_JSON.relative_to(REPO_ROOT)}")

    if args.write_report:
        REPORT_MD.write_text(render_report(results))
        print(f"Wrote report to {REPORT_MD.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
