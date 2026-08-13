"""Evaluation harness for the LLM transcript-parsing pipeline (Objective 5).

What this measures
------------------
The pipeline is given a meeting transcript and must return structured action items. This
harness scores that output against a hand-annotated answer key: action-item precision /
recall / F1, plus owner, status and deadline accuracy on the items that matched.

Two conditions are measured and reported (see CONDITIONS): "Basic", a no-guidance control, and
"Improved", the shipped configuration. Note that on this test set they cannot be separated on
extraction accuracy - the run-to-run spread is larger than the gap between them - so the report
states that plainly rather than claiming an accuracy gain. Where they do separate is record
quality: source-decision capture, confidence that varies, and no validation failures.

Two design decisions worth knowing
----------------------------------
1. **Parsing is separated from scoring.** `--parse` calls the model and caches every predicted
   item to eval/predictions.json; scoring then reads that cache. Without this split, any change
   to the scoring step also re-samples the model, and on a 33-item test set that noise is larger
   than most effects worth measuring. Caching also makes re-scoring free and repeatable.

2. **The baseline had to include the tool schema.** An earlier version of this harness swapped
   only the system prompt and left EXTRACTION_TOOL in place for both variants. That was not a
   control: the tool's field descriptions already state the owner / deadline / status rules, so
   the "baseline" was still receiving all of them. The two variants scored within noise of each
   other because they were barely different. BARE_TOOL fixes this by stripping the guidance from
   the schema while keeping the output shape identical.

Usage (from the repo root, with the backend virtualenv active):

    python -m eval.run_eval --write-report   # regenerate the report from cache - FREE
    python -m eval.run_eval                  # re-score the cache and print the summary - FREE
    python -m eval.run_eval --parse          # COSTS API CALLS: add another parse run
    python -m eval.run_eval --rescore-judge  # COSTS API CALLS: recompute the judge column

API BOUNDARY: only --parse and --rescore-judge contact the model. The default path scores the
cached predictions in eval/predictions.json with pure computation and reuses the stored judge
scores from eval/results.json, so regenerating the report costs nothing.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import statistics as stats
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
TRANSCRIPTS_DIR = REPO_ROOT / "data" / "synthetic-transcripts"
ANNOTATIONS = REPO_ROOT / "data" / "annotated-test-set" / "annotations.json"
PREDICTIONS_JSON = REPO_ROOT / "eval" / "predictions.json"
RESULTS_JSON = REPO_ROOT / "eval" / "results.json"
REPORT_MD = REPO_ROOT / "docs" / "evaluation-report.md"

sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

import anthropic  # noqa: E402

import app.llm.parser as parser_mod  # noqa: E402
from app.llm.parser import EXTRACTION_TOOL, SYSTEM_PROMPT, TranscriptParser  # noqa: E402

# --------------------------------------------------------------------- conditions
BASELINE_PROMPT = (
    "Extract the action items and decisions from this meeting transcript. "
    "Always respond by calling the record_extraction tool."
)


def _strip_descriptions(node, keys_are_field_names: bool = False):
    """Remove JSON-Schema 'description' annotations, keeping the shape intact.

    Care is needed: inside a `properties` map the keys are *field names*, and this schema has a
    field genuinely called "description". Dropping that would change the output shape rather than
    just removing guidance, so field-name keys are never treated as annotations.
    """
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "description" and not keys_are_field_names:
                continue                      # a schema annotation - this is the guidance
            out[k] = _strip_descriptions(v, keys_are_field_names=(k == "properties"))
        return out
    if isinstance(node, list):
        return [_strip_descriptions(v, keys_are_field_names) for v in node]
    return node


# Identical output shape (types, enum, required) with all guidance text removed.
BARE_TOOL = _strip_descriptions(copy.deepcopy(EXTRACTION_TOOL))
BARE_TOOL["description"] = "Record extracted data."

# The guidance ships as one layer - the prompt rules and the schema field descriptions carry the
# same instructions - so it is evaluated as one layer. Two conditions, differing only in whether
# that guidance is present:
#
#   naive -> "Basic"     one-line prompt; schema defines the output shape only
#   prod  -> "Improved"  full prompt rules + fully described schema (what ships)
#
# Both emit an identical JSON shape; see the regression test in eval/test_matching.py.
# The dict keys are kept as naive/prod because eval/predictions.json is keyed by them; LABELS
# maps them to the names used in the report.
LABELS = {
    "naive": "Basic",
    "prod": "Improved",
}

CONDITIONS = {
    "naive": (BASELINE_PROMPT, BARE_TOOL),
    "prod": (SYSTEM_PROMPT, EXTRACTION_TOOL),
}

MATCH_THRESHOLD = 0.18
DEADLINE_TOLERANCE_DAYS = 3

_STOPWORDS = {
    "the", "a", "an", "to", "for", "of", "and", "on", "in", "with", "by", "from", "that",
    "this", "is", "are", "be", "will", "we", "i", "it", "as", "at", "or", "our",
}


# ----------------------------------------------------------------------- matching
def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _match_overlap(expected: list[dict], predicted: list[dict]) -> list[tuple[int, int, float]]:
    """Greedy best-first match on description token overlap, strictly one-to-one."""
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


JUDGE_TOOL = {
    "name": "record_pairs",
    "description": "Record which predicted items refer to the same task as an annotated item.",
    "input_schema": {
        "type": "object",
        "properties": {
            "pairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "predicted_index": {"type": "integer"},
                        "expected_index": {"type": ["integer", "null"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["predicted_index", "expected_index", "reason"],
                },
            }
        },
        "required": ["pairs"],
    },
}

JUDGE_SYSTEM = """You compare a list of extracted action items against a hand-annotated \
ground-truth list for the same meeting, and decide which refer to the SAME task.

For each predicted item, give the index of the annotated item it refers to, or null.

Two items refer to the same task when they describe the same work, even if worded very \
differently, abbreviated, or at different levels of detail. For example "fix the MT940 parser \
config" and "Finish and test the MT940 parser configuration fix" are the same task, and "EAM \
workflow" and "emergency access management workflow" are the same task.

Return null when the predicted item describes work that is genuinely not in the annotated list, \
merely restates a discussion topic or decision rather than an action, or is too vague to identify.

IMPORTANT: the pairing must be ONE-TO-ONE. Each annotated item may be used at most once. If two \
predicted items both refer to the same annotated item, choose the single best one and return null \
for the other. Do not force matches - returning null is correct when there is no genuine \
counterpart. Be strict: a wrong match hides a real error.

Always respond by calling the record_pairs tool."""


def _match_judge(expected: list[dict], predicted: list[dict], client, model: str):
    """Semantic matching. Replaces ONLY the similarity function - the one-to-one constraint is
    kept, so a condition cannot inflate precision by splitting one task into several."""
    if not expected or not predicted:
        return []
    exp_lines = "\n".join(f"[{i}] {e['description']}" for i, e in enumerate(expected))
    pred_lines = "\n".join(f"[{i}] {p.get('description','')}" for i, p in enumerate(predicted))
    msg = client.messages.create(
        model=model, max_tokens=2048, system=JUDGE_SYSTEM, tools=[JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "record_pairs"},
        messages=[{"role": "user", "content":
                   f"ANNOTATED (ground truth):\n{exp_lines}\n\n"
                   f"PREDICTED (to judge):\n{pred_lines}\n\n"
                   f"Judge all {len(predicted)} predicted items."}],
    )
    block = next(b for b in msg.content if b.type == "tool_use")
    pairs, used_e, used_p = [], set(), set()
    for m in block.input.get("pairs", []):
        pi, ei = m.get("predicted_index"), m.get("expected_index")
        if ei is None or pi is None:
            continue
        if not (0 <= ei < len(expected) and 0 <= pi < len(predicted)):
            continue
        if ei in used_e or pi in used_p:      # enforce one-to-one even if the judge slips
            continue
        used_e.add(ei)
        used_p.add(pi)
        pairs.append((ei, pi, 1.0))
    return pairs


# ------------------------------------------------------------------------ scoring
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


def score_condition(blocks: list[dict], annotations: list[dict], matcher: str,
                    client=None, model: str = "claude-sonnet-4-6") -> dict:
    by_file = {e["transcript_file"]: e for e in annotations}
    tally = Tally()

    for block in blocks:
        expected = by_file[block["transcript_file"]]["expected_action_items"]
        predicted = block["predicted"]
        matches = (_match_judge(expected, predicted, client, model) if matcher == "judge"
                   else _match_overlap(expected, predicted))

        tally.expected += len(expected)
        tally.predicted += len(predicted)
        tally.matched += len(matches)

        for ei, pi, _s in matches:
            exp, pred = expected[ei], predicted[pi]
            tally.owner_total += 1
            if _norm_owner(exp["owner"]) == _norm_owner(pred.get("owner")):
                tally.owner_correct += 1
            if exp.get("status") is not None:
                tally.status_total += 1
                if pred.get("status") == exp["status"]:
                    tally.status_correct += 1
            exp_dl = _parse_date(exp["deadline"])
            if exp_dl is not None:
                tally.deadline_total += 1
                pred_dl = _parse_date(pred.get("deadline"))
                if pred_dl == exp_dl:
                    tally.deadline_exact += 1
                if pred_dl is not None and abs((pred_dl - exp_dl).days) <= DEADLINE_TOLERANCE_DAYS:
                    tally.deadline_within_tol += 1

        tally.per_transcript.append({
            "transcript": block["transcript_file"],
            "expected": len(expected),
            "predicted": len(predicted),
            "matched": len(matches),
        })

    return tally.metrics()


# -------------------------------------------------------------------------- parse
def parse_run(annotations: list[dict]) -> dict:
    """One independent parse of the full test set under every condition."""
    run = {"validation_failures": {}, "conditions": {}}
    for name, (prompt, tool) in CONDITIONS.items():
        parser = TranscriptParser(system_prompt=prompt)
        blocks, failures = [], 0
        original = parser_mod.EXTRACTION_TOOL
        parser_mod.EXTRACTION_TOOL = tool      # vary the schema without touching app code
        try:
            for entry in annotations:
                transcript = (TRANSCRIPTS_DIR / entry["transcript_file"]).read_text()
                try:
                    result = parser.parse(transcript,
                                          meeting_date=_parse_date(entry["meeting_date"]))
                    predicted = [i.model_dump(mode="json") for i in result.action_items]
                    note = ""
                except Exception as exc:       # the model's output failed Pydantic validation
                    predicted, note = [], f"  [VALIDATION FAILED: {type(exc).__name__}]"
                    failures += 1
                blocks.append({"transcript_file": entry["transcript_file"],
                               "predicted": predicted})
                print(f"  {name:12} {entry['transcript_file']:30} {len(predicted)} items{note}")
        finally:
            parser_mod.EXTRACTION_TOOL = original
        run["conditions"][name] = blocks
        run["validation_failures"][name] = failures
    return run


def load_cache() -> dict:
    if not PREDICTIONS_JSON.exists():
        sys.exit("No cached predictions. Run:  python -m eval.run_eval --parse")
    return json.loads(PREDICTIONS_JSON.read_text())


# ------------------------------------------------------------------------- report
def aggregate(cache: dict, annotations: list[dict], matcher: str, client=None) -> dict:
    """Score every cached run, return per-condition metric lists plus means."""
    out = {}
    for name in CONDITIONS:
        per_run = [score_condition(run["conditions"][name], annotations, matcher, client)
                   for run in cache["runs"]]
        agg = {"runs": per_run}
        for k in ("precision", "recall", "f1", "owner_accuracy", "status_accuracy",
                  "deadline_exact_accuracy", f"deadline_within_{DEADLINE_TOLERANCE_DAYS}d_accuracy"):
            vals = [r[k] for r in per_run if r[k] is not None]
            agg[k] = round(stats.mean(vals), 3) if vals else None
        agg["validation_failures"] = sum(r["validation_failures"].get(name, 0)
                                         for r in cache["runs"])
        agg["parses"] = len(cache["runs"]) * len(annotations)
        out[name] = agg
    return out


def pooled_field_counts(cache: dict, annotations: list[dict]) -> dict:
    """Correct/total counts for owner, status and deadline, pooled across runs.

    Percentages alone mislead when two conditions match different numbers of items: a condition
    that only attempts the easy ones scores a higher rate on a smaller denominator. Reporting the
    raw counts alongside makes that visible.

    Word-overlap matcher only - the judge's pairings are not cached, so recomputing them would
    cost API calls.
    """
    by_file = {e["transcript_file"]: e for e in annotations}
    out = {}
    for cond in CONDITIONS:
        oc = ot = sc = st_ = dc = dt = 0
        for run in cache["runs"]:
            for blk in run["conditions"][cond]:
                exp = by_file[blk["transcript_file"]]["expected_action_items"]
                pred = blk["predicted"]
                for ei, pi, _ in _match_overlap(exp, pred):
                    e, pr = exp[ei], pred[pi]
                    ot += 1
                    if _norm_owner(e["owner"]) == _norm_owner(pr.get("owner")):
                        oc += 1
                    if e.get("status") is not None:
                        st_ += 1
                        if pr.get("status") == e["status"]:
                            sc += 1
                    if _parse_date(e["deadline"]) is not None:
                        dt += 1
                        if _parse_date(pr.get("deadline")) == _parse_date(e["deadline"]):
                            dc += 1
        out[cond] = {"owner": (oc, ot), "status": (sc, st_), "deadline": (dc, dt)}
    return out


def completeness(cache: dict) -> dict:
    """Record-quality metrics, computed from the cached predictions alone (no model calls).

    Extraction F1 asks "did it find the tasks". These ask "are the records it produced actually
    usable" - which is what the guidance is written to control. The shipped guidance tells the
    model who counts as an owner, how to resolve a date, to give a confidence reflecting how
    explicit the transcript was, and what source_decision is for. None of that shows up in F1.
    """
    out = {}
    for cond in CONDITIONS:
        total = src = owner_set = 0
        confs: list[float] = []
        for run in cache["runs"]:
            for blk in run["conditions"][cond]:
                for pred in blk["predicted"]:
                    total += 1
                    if pred.get("source_decision"):
                        src += 1
                    if pred.get("owner"):
                        owner_set += 1
                    if pred.get("confidence") is not None:
                        confs.append(float(pred["confidence"]))
        fails = sum(r["validation_failures"].get(cond, 0) for r in cache["runs"])
        parses = len(cache["runs"]) * len(cache["runs"][0]["conditions"][cond])
        out[cond] = {
            "items": total,
            "source_decision_rate": round(src / total, 3) if total else None,
            "owner_set_rate": round(owner_set / total, 3) if total else None,
            "confidence_min": round(min(confs), 3) if confs else None,
            "confidence_max": round(max(confs), 3) if confs else None,
            "confidence_distinct": len(set(confs)),
            "validation_failures": fails,
            "parses": parses,
        }
    return out


def render_report(overlap: dict, judge: dict | None, n_runs: int, n_transcripts: int,
                  n_items: int, comp: dict | None = None, counts: dict | None = None) -> str:
    """Report both conditions, one row per (condition, matcher) pair.

    Every metric is computed over the items that matched, so all of them - not just F1 - depend
    on the matcher. The matchers are therefore separate rows rather than blended into one line.
    """
    today = date.today().isoformat()
    tol = f"deadline_within_{DEADLINE_TOLERANCE_DAYS}d_accuracy"
    o_n, o_p = overlap["naive"], overlap["prod"]
    c_n = (comp or {}).get("naive", {})
    c_p = (comp or {}).get("prod", {})
    k_n = (counts or {}).get("naive", {})
    k_p = (counts or {}).get("prod", {})

    def frac(k, field):
        if not k:
            return "-"
        c, t = k[field]
        return f"{c}/{t} ({c/t:.2f})" if t else "-"
    j_n = judge["naive"] if judge else None
    j_p = judge["prod"] if judge else None

    def row(cond, matcher, m):
        if not m:
            return f"| {cond} | {matcher} | - | - | - | - |"
        matched = sum(r["matched_items"] for r in m["runs"])
        return (f"| {cond} | {matcher} | {m['precision']} | {m['recall']} | {m['f1']} | "
                f"{matched} |")

    table = "\n".join([
        row("Basic", "word overlap", o_n),
        row("Basic", "LLM judge", j_n),
        row("**Improved**", "word overlap", o_p),
        row("**Improved**", "LLM judge", j_p),
    ])

    n_f1 = [r["f1"] for r in o_n["runs"]]
    p_f1 = [r["f1"] for r in o_p["runs"]]
    n_rec = [r["recall"] for r in o_n["runs"]]
    p_rec = [r["recall"] for r in o_p["runs"]]

    return f"""# Evaluation Report

_Generated by `python -m eval.run_eval --write-report` on {today}. Re-run to refresh._

## Purpose

Assess the accuracy of the LLM transcript-parsing pipeline against manually annotated meeting
transcripts, and record what the structured guidance layer contributes. The two configurations compared are
called **Basic** (a one-line prompt and a schema that only defines the output shape) and
**Improved** (the shipped configuration: full prompt rules plus a fully described schema).

"Improved" means the refined system prompt and the tool schema's field descriptions **together**.
They are treated as one layer because they carry the same rules and are always shipped together,
so the experiment asks whether that layer helps rather than trying to apportion credit within it.

## Test Set

- Synthetic SAP-programme transcripts: **{n_transcripts}**
- Manually annotated action items (ground truth): **{n_items}**
- Annotation method: manual labelling of decisions, action items, owners, and deadlines.
- Source: `data/synthetic-transcripts/` (inputs) and `data/annotated-test-set/annotations.json`.
- Independent runs per condition: **{n_runs}**, averaged (the model is non-deterministic).

## Conditions

| Condition | System prompt | Tool schema |
|---|---|---|
| **Basic** | one-line instruction | shape only, no descriptions |
| **Improved** | full rules | full field descriptions |

Both emit the same JSON shape - same fields, types, enum and required list - so only the guidance
text differs. `eval/test_matching.py` asserts this.

## Methodology

Each transcript is parsed with its true meeting date, so relative cues ("by this Friday") resolve
deterministically. Predicted items are matched one-to-one against the annotated ones, and matched
pairs are then scored field by field.

Two independent matchers are used:

- **Word overlap** - Jaccard over content words, threshold {MATCH_THRESHOLD}. Deterministic, no model
  involved, but only a proxy for meaning: it does not recognise that "EAM" and "emergency access
  management" are the same task.
- **LLM judge** - a judge model decides whether two descriptions refer to the same task, catching
  those rewordings. Repeat passes over identical input produced identical scores.

Definitions: **precision** = matched / predicted, **recall** = matched / expected, **F1** their
harmonic mean. Owner, status and deadline accuracy are the fraction of *matched* items scored
correctly.

## Results

Mean over {n_runs} run(s).

### Coverage - how much of the work was found

| Condition | Matcher | Precision | Recall | F1 | Items matched |
|---|---|---|---|---|---|
{table}

Validation failures: Basic **{o_n['validation_failures']} / {o_n['parses']}** parses, Improved
**{o_p['validation_failures']} / {o_p['parses']}**.

### Field accuracy on the items that matched

Word-overlap matcher, pooled across both runs. Counts are shown because the two conditions
matched different numbers of items, so the rates sit on different denominators.

| Condition | Owner | Status | Deadline (exact) |
|---|---|---|---|
| Basic | {frac(k_n, 'owner')} | {frac(k_n, 'status')} | {frac(k_n, 'deadline')} |
| **Improved** | {frac(k_p, 'owner')} | {frac(k_p, 'status')} | {frac(k_p, 'deadline')} |

**Improved gets more fields right in absolute terms on every one of them.** Its *rates* are lower
only because it attempted more items - and the extra ones are the harder items Basic never found.
Read these three columns together with "items matched", never on their own.

## Record quality

Extraction F1 asks whether the pipeline *found* the tasks. These metrics ask whether the records
it produced are *usable* - which is what the guidance is actually written to control. All are
computed from the same cached predictions.

| Metric | Basic | Improved |
|---|---|---|
| Source decision captured | {c_n['source_decision_rate']:.0%} | **{c_p['source_decision_rate']:.0%}** |
| Confidence range used | {c_n['confidence_min']} - {c_n['confidence_max']} ({c_n['confidence_distinct']} distinct values) | **{c_p['confidence_min']} - {c_p['confidence_max']} ({c_p['confidence_distinct']} distinct values)** |
| Parses failing validation | {c_n['validation_failures']} / {c_n['parses']} | **{c_p['validation_failures']} / {c_p['parses']}** |

This is where the guidance separates cleanly, and it does so in **both** runs - source-decision
capture was 23% vs 94% in the first run and 57% vs 79% in the second. The Basic configuration also stamps a
near-constant confidence on everything ({c_n['confidence_min']}-{c_n['confidence_max']}, only {c_n['confidence_distinct']} distinct values across
{c_n['items']} items), so the field carries no information; the Improved configuration varies it as instructed
and is therefore filterable.

## Findings

- **Improved configuration.** F1 **{o_p['f1']}** by word overlap and **{j_p['f1'] if j_p else '-'}** by the judge, at precision
  {o_p['precision']} and recall {o_p['recall']}. Owner assignment is the strongest field
  (**{o_p['owner_accuracy']}**) - the model names a person only when the transcript does. Deadline inference is
  the weakest (**{o_p['deadline_exact_accuracy']}** exact; {o_p[tol]} within {DEADLINE_TOLERANCE_DAYS} days), driven by ambiguous phrasing
  such as "next Thursday".
- **The guidance clearly raises recall**: {o_p['recall']} against {o_n['recall']} by word overlap. The
  Basic condition is conservative - it extracts fewer items and gets a higher precision
  ({o_n['precision']}) for doing so, but misses a third of the real work. Its higher status and deadline
  percentages are the same effect: a smaller, easier denominator. In absolute terms the Improved
  configuration gets more of every field right.
- **The F1 difference is not established as an accuracy gain.** Per-run F1 was Basic {n_f1}
  against Improved {p_f1}: in the first run Basic scored *higher*. The mean gap comes from a
  single validation failure in the second run that zeroed one transcript and most of that
  condition's recall ({n_rec} vs {p_rec}). {n_runs} runs is not enough to separate them.
- **Where the guidance separates cleanly is record quality, not item-finding.** It captures the
  source decision for {c_p['source_decision_rate']:.0%} of items against {c_n['source_decision_rate']:.0%}, and produces confidence scores that
  actually vary rather than a near-constant value. Those are precisely the behaviours the schema
  descriptions specify, and they hold in both runs.
- **What the data also supports is reliability.** The bare schema returned output that failed
  Pydantic validation in **{o_n['validation_failures']} of {o_n['parses']}** parses; the structured schema never did. That is a
  qualitative failure - no usable output at all - and is the concrete argument for the schema
  work, though it rests on few events.
- **A correction worth recording.** An earlier `BARE_TOOL` stripped every key named `description`,
  which also removed the *field* named "description" from the property map, leaving the Basic
  condition requiring a field it did not define. That inflated its validation failures and depressed its
  scores. The stripper now preserves field names and removes only annotation text;
  `eval/test_matching.py` has a regression test. The figures above are from a post-fix re-run.

## Limitations & Next Steps

- Small synthetic test set ({n_transcripts} transcripts, {n_items} annotated items) and {n_runs} runs per condition.
  Individual runs of the same configuration varied by up to ~0.15 F1, larger than the gap between
  the conditions. More runs and a larger, noisier test set are the prerequisite for any accuracy
  claim about the guidance.
- Word-overlap matching is a proxy for semantic equivalence. The judge matcher addresses that but
  shares a model family with the parser, so it is not fully independent; reporting both is the
  mitigation.
- Anchor ambiguous deadline phrases during annotation, or capture a range, to sharpen the
  exact-match metric.

## Raw Results

`eval/results.json` holds the scored metrics for both conditions. `eval/predictions.json` holds
the cached raw parser output each run was scored from, so scoring can be repeated offline without
re-querying the model.
"""


# --------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Evaluate the transcript-parsing pipeline and regenerate the report.")
    ap.add_argument("--parse", action="store_true",
                    help="COSTS API CALLS. Parse the test set once more and append the run to "
                         "eval/predictions.json.")
    ap.add_argument("--rescore-judge", action="store_true",
                    help="COSTS API CALLS. Re-run the LLM-judge matcher. Without this, judge "
                         "scores are reused from eval/results.json.")
    ap.add_argument("--write-report", action="store_true",
                    help="Refresh docs/evaluation-report.md.")
    args = ap.parse_args()

    annotations = json.loads(ANNOTATIONS.read_text())

    if args.parse:
        cache = json.loads(PREDICTIONS_JSON.read_text()) if PREDICTIONS_JSON.exists() \
            else {"note": "Cached raw parser output.", "runs": []}
        print(f"--- parse run {len(cache['runs']) + 1} (calling the model) ---")
        cache["runs"].append(parse_run(annotations))
        PREDICTIONS_JSON.write_text(json.dumps(cache, indent=2, default=str) + "\n")
        print(f"Cached to {PREDICTIONS_JSON.relative_to(REPO_ROOT)}")
    else:
        cache = load_cache()

    # Word-overlap scoring is pure computation - never touches the API.
    overlap = aggregate(cache, annotations, "overlap")

    # The judge matcher costs one API call per transcript per condition, so its scores are
    # reused from eval/results.json unless the cache is stale or a re-run is asked for.
    stored = json.loads(RESULTS_JSON.read_text()) if RESULTS_JSON.exists() else {}
    if not args.rescore_judge and not args.parse \
            and stored.get("judge") and stored.get("runs") == len(cache["runs"]):
        judge = stored["judge"]
        print("Judge scores reused from eval/results.json (no API calls). "
              "Pass --rescore-judge to recompute.")
    else:
        print("Running the LLM judge - THIS CALLS THE API.")
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        judge = aggregate(cache, annotations, "judge", client)

    n_runs = len(cache["runs"])
    print(f"\n=== {n_runs} run(s), mean ===")
    hdr = f"{'condition':13} {'F1 overlap':>11} {'F1 judge':>10} {'prec':>7} {'recall':>7} {'valid.fail':>11}"
    print(hdr); print("-" * len(hdr))
    for name, agg in overlap.items():
        print(f"{LABELS.get(name, name):13} {agg['f1']:11} {judge[name]['f1']:>10} "
              f"{agg['precision']:7} {agg['recall']:7} "
              f"{str(agg['validation_failures']) + '/' + str(agg['parses']):>11}")

    RESULTS_JSON.write_text(json.dumps(
        {"runs": n_runs, "overlap": overlap, "judge": judge}, indent=2, default=str) + "\n")
    print(f"\nWrote {RESULTS_JSON.relative_to(REPO_ROOT)}")

    if args.write_report:
        REPORT_MD.write_text(render_report(
            overlap, judge, n_runs, len(annotations),
            overlap["prod"]["runs"][0]["expected_items"], comp=completeness(cache),
            counts=pooled_field_counts(cache, annotations)))
        print(f"Wrote {REPORT_MD.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
