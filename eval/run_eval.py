"""Evaluation framework for the LLM transcript-parsing pipeline (Objective 5).

What this measures
------------------
The pipeline is given a meeting transcript and must return structured action items. This
framework scores that output against a hand-annotated answer key: action-item precision /
recall / F1, plus owner, status and deadline accuracy on the items that matched.

Two test sets are scored:

* **short** - four ~1,000-word transcripts (33 items). The prompt was refined against these, so
  they are the development set.
* **long** - four 3,100-4,100-word transcripts (123 items), written after the prompt was fixed
  and never used to tune it. They are the held-out set, and test whether the model choice holds
  on longer meetings with more people, revised deadlines and cancelled requests.

Two questions are answered, by two sets of conditions (see CONDITIONS):

1. **Does the guidance layer help?** Guidance level (without guidance, or the with-guidance
   configuration the project implements) crossed with model family (Claude Sonnet, Gemini Flash).
2. **Which model should the project use?** Claude Sonnet, Claude Haiku and Gemini Flash, all on
   the with-guidance configuration. Tiers and release dates differ in both directions, so this is
   a decision for this project, not a vendor ranking.

Every configuration is run eight times per set, and differences are tested with an exact
permutation test over the per-run scores (permutation_test).

Design decisions worth knowing
------------------------------
1. **Parsing is separated from scoring.** `--parse` calls the model and caches every predicted
   item (eval/predictions.json, eval/predictions_long.json); scoring reads the caches. A change
   to scoring therefore never re-samples the model, and re-scoring is free and repeatable.

2. **The without-guidance configuration had to strip the tool schema too.** The tool's field
   descriptions state the owner / deadline / status rules, so swapping only the system prompt
   would leave them in place. BARE_TOOL removes the guidance from the schema while keeping the
   output shape identical.

3. **Each run holds one model group.** A `--parse` invocation records one group, so every
   aggregate filters with `runs_with()`, and adding runs for one model cannot disturb another's.

4. **API failures are not model failures.** A request that never completed (rate limit,
   capacity) is marked and excluded from scoring. Only responses that arrived but did not satisfy
   the schema count as validation failures.

5. **The provider is always named.** The Claude conditions pass provider="anthropic" explicitly;
   otherwise they would follow LLM_PROVIDER, which the deployment sets to gemini.

Usage (from the repo root, with the backend virtualenv active):

    python -m eval.run_eval --write-report                            # regenerate - FREE
    python -m eval.run_eval                                           # re-score - FREE
    python -m eval.run_eval --parse --set long --provider gemini --runs 8   # Gemini credit
    python -m eval.run_eval --parse --set long --provider haiku --runs 8    # Anthropic credit
    python -m eval.run_eval --parse --set long --provider claude --runs 8   # Anthropic credit
    python -m eval.run_eval --rescore-judge                           # Anthropic credit

API BOUNDARY: only `--parse` and `--rescore-judge` contact a model. The default path scores the
cached predictions with pure computation, so regenerating the report costs nothing.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import os
import re
import statistics as stats
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
TRANSCRIPTS_DIR = REPO_ROOT / "data" / "synthetic-transcripts"
ANNOTATIONS = REPO_ROOT / "data" / "annotated-test-set" / "annotations.json"
PREDICTIONS_JSON = REPO_ROOT / "eval" / "predictions.json"
# The long set is held out: written after the prompt was fixed and never used to tune it, so it
# tests whether the model choice survives meetings the prompt was not shaped around.
LONG_TRANSCRIPTS_DIR = REPO_ROOT / "data" / "synthetic-transcripts-long"
LONG_ANNOTATIONS = REPO_ROOT / "data" / "annotated-test-set-long" / "annotations.json"
LONG_PREDICTIONS_JSON = REPO_ROOT / "eval" / "predictions_long.json"
TEST_SETS = {
    "short": (TRANSCRIPTS_DIR, ANNOTATIONS, PREDICTIONS_JSON),
    "long": (LONG_TRANSCRIPTS_DIR, LONG_ANNOTATIONS, LONG_PREDICTIONS_JSON),
}
RESULTS_JSON = REPO_ROOT / "eval" / "results.json"
# Two documents on purpose. The report has to be readable in a couple of minutes; the appendix
# carries the method, every condition on every set, and the limitations. The report links to the
# appendix for every claim it compresses.
REPORT_MD = REPO_ROOT / "docs" / "evaluation-report.md"
APPENDIX_MD = REPO_ROOT / "docs" / "evaluation-appendix.md"

sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

import anthropic  # noqa: E402

import app.llm.parser as parser_mod  # noqa: E402
from app.llm.parser import EXTRACTION_TOOL, SYSTEM_PROMPT, TranscriptParser  # noqa: E402
from eval.providers import ProviderError  # noqa: E402

# Failures that mean "the provider never gave us an answer" - rate limits, capacity, transport.
# These are excluded from scoring rather than counted against the condition; see parse_run.
_API_FAILURES = (
    ProviderError,
    anthropic.APIConnectionError,
    anthropic.APIStatusError,   # 429/5xx after the SDK's own retries
)

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

# The guidance is implemented as one layer - the prompt rules and the schema field descriptions
# carry the same instructions - so it is evaluated as one layer, crossed with model family:
#
#                  Without guidance              With guidance
#   Claude         naive                         prod
#   Gemini         gemini_naive                  gemini_prod
#
# Running it on two model families shows whether an effect belongs to the guidance or to one
# vendor's tool use. The results themselves are computed and written by render_appendix.
#
# Both tools emit an identical JSON shape (eval/test_matching.py asserts it for Claude,
# eval/test_providers.py for Gemini after schema translation).
#
# The Claude keys stay "naive"/"prod" because eval/predictions.json is already keyed by them.


@dataclass(frozen=True)
class Condition:
    label: str          # how the report names it, e.g. "With guidance (Gemini Flash)"
    provider: str       # "claude" | "gemini" - which adapter drives it
    guidance: str       # "Basic" | "Improved" - the axis being ablated
    prompt: str
    tool: dict
    group: str          # --parse selector. Separate from provider so Haiku can be run
                        # without also re-billing the Sonnet conditions.
    short: str          # model name alone, for tables where guidance is fixed and only the
                        # model varies. Stored rather than sliced out of `label`.
    model: str | None = None   # None -> that provider's configured default


CONDITIONS = {
    # The guidance 2x2.
    "naive":        Condition("Without guidance (Claude Sonnet)", "claude", "Basic",
                              BASELINE_PROMPT, BARE_TOOL, group="claude", short="Claude Sonnet"),
    "prod":         Condition("With guidance (Claude Sonnet)", "claude", "Improved",
                              SYSTEM_PROMPT, EXTRACTION_TOOL, group="claude", short="Claude Sonnet"),
    "gemini_naive": Condition("Without guidance (Gemini Flash)", "gemini", "Basic",
                              BASELINE_PROMPT, BARE_TOOL, group="gemini", short="Gemini Flash"),
    "gemini_prod":  Condition("With guidance (Gemini Flash)", "gemini", "Improved",
                              SYSTEM_PROMPT, EXTRACTION_TOOL, group="gemini", short="Gemini Flash"),
    # Model comparison, with-guidance configuration only: the guidance question is answered by
    # the four conditions above, and "which model should this product use?" is asked under the
    # configuration the application actually runs.
    "haiku_prod":   Condition("With guidance (Claude Haiku)", "claude", "Improved",
                              SYSTEM_PROMPT, EXTRACTION_TOOL, group="haiku",
                              short="Claude Haiku", model="claude-haiku-4-5"),
}

LABELS = {key: cond.label for key, cond in CONDITIONS.items()}

# --parse operates on one group at a time, so a run never mixes providers.
GROUPS = sorted({c.group for c in CONDITIONS.values()})

# The model-choice comparison, all on the with-guidance configuration. Claude Sonnet was the
# original model, so it is included: the question is whether to replace it. The tiers differ in
# both directions (Sonnet is a larger tier, Gemini Flash a later release), which is why this is
# reported as a decision for this project rather than a vendor ranking.
COMPARISON_CONDITIONS = ["prod", "haiku_prod", "gemini_prod"]


def runs_with(cache: dict, cond: str) -> list[dict]:
    """The cached runs that actually contain this condition.

    Each `--parse` invocation records one provider, so a run holds either the Claude conditions
    or the Gemini ones - never both. Every aggregate therefore has to filter rather than assume
    a uniform run list, or the Claude figures would change the moment a Gemini run is added.
    """
    return [r for r in cache["runs"] if cond in r.get("conditions", {})]

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

    for block in scorable(blocks):
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
def scorable(blocks: list[dict]) -> list[dict]:
    """Blocks the provider actually answered.

    A block marked `error: "api"` means the request never completed, so there is no prediction to
    score. Including it would count a rate limit as the model finding nothing.
    """
    return [b for b in blocks if b.get("error") != "api"]


def _make_parser(cond: Condition):
    """Build a parser for one condition. All of them expose .parse(text, meeting_date).

    Claude varies its schema by monkey-patching the module global the app parser reads, so the
    application's own code path is exercised as-is; the second return value is the tool to patch in. The
    other providers take the tool as a constructor argument (eval/providers.py) and so return
    None for it.
    """
    if cond.provider == "gemini":
        from eval.providers import GeminiParser
        return GeminiParser(cond.prompt, cond.tool, model=cond.model), None
    # The provider is named explicitly. Left to default, TranscriptParser follows LLM_PROVIDER,
    # which the deployment sets to gemini - and every "Claude" condition would silently run on
    # Gemini while being labelled as Claude.
    return (TranscriptParser(system_prompt=cond.prompt, model=cond.model, provider="anthropic"),
            cond.tool)


def parse_run(annotations: list[dict], conditions: list[str],
              transcripts_dir: Path = TRANSCRIPTS_DIR) -> dict:
    """One independent parse of the full test set under each named condition.

    Two kinds of failure are recorded separately, and the distinction matters:

    * **validation failure** - the model answered, but its output did not satisfy the schema.
      That is a genuine quality signal and one of the headline results, so it counts.
    * **API failure** - the provider never returned a usable answer (rate limit, capacity). That
      says nothing about the model's extraction quality. Counting it would penalise whichever
      condition happened to be running when a quota ran out, so these blocks are marked and
      excluded from scoring entirely rather than being scored as "found nothing".
    """
    run = {"validation_failures": {}, "api_failures": {}, "conditions": {}, "models": {}}
    for name in conditions:
        cond = CONDITIONS[name]
        parser, claude_tool = _make_parser(cond)
        # Recorded per run: which model produced these predictions. Without it a cache spanning
        # a model change is unreadable after the fact.
        run["models"][name] = getattr(parser, "model", "?")
        blocks, failures, api_failures = [], 0, 0
        original = parser_mod.EXTRACTION_TOOL
        if claude_tool is not None:
            parser_mod.EXTRACTION_TOOL = claude_tool   # vary schema without touching app code
        try:
            for entry in annotations:
                transcript = (transcripts_dir / entry["transcript_file"]).read_text()
                block = {"transcript_file": entry["transcript_file"], "predicted": []}
                try:
                    result = parser.parse(transcript,
                                          meeting_date=_parse_date(entry["meeting_date"]))
                    block["predicted"] = [i.model_dump(mode="json")
                                          for i in result.action_items]
                    note = ""
                except _API_FAILURES as exc:   # provider never answered - not a quality signal
                    block["error"] = "api"
                    api_failures += 1
                    note = f"  [API FAILURE - excluded: {str(exc)[:60]}]"
                except Exception as exc:       # the model answered, but off-schema
                    failures += 1
                    note = f"  [VALIDATION FAILED: {type(exc).__name__}]"
                blocks.append(block)
                print(f"  {name:14} {entry['transcript_file']:30} "
                      f"{len(block['predicted'])} items{note}", flush=True)
        finally:
            parser_mod.EXTRACTION_TOOL = original
        run["conditions"][name] = blocks
        run["validation_failures"][name] = failures
        run["api_failures"][name] = api_failures
    return run


def load_cache() -> dict:
    if not PREDICTIONS_JSON.exists():
        sys.exit("No cached predictions. Run:  python -m eval.run_eval --parse")
    return json.loads(PREDICTIONS_JSON.read_text())


# ------------------------------------------------------------------------- report
def aggregate(cache: dict, annotations: list[dict], matcher: str, client=None,
              only: list[str] | None = None) -> dict:
    """Score every cached run, return per-condition metric lists plus means.

    `only` restricts scoring to named conditions, which matters for the judge matcher: it costs
    an API call per transcript, so already-scored conditions are reused rather than recomputed.
    """
    out = {}
    for name in (only if only is not None else list(CONDITIONS)):
        runs = runs_with(cache, name)
        if not runs:
            continue                       # condition has never been parsed - omit it entirely
        per_run = [score_condition(run["conditions"][name], annotations, matcher, client)
                   for run in runs]
        agg_api_failures = sum(r.get("api_failures", {}).get(name, 0) for r in runs)
        agg = {"runs": per_run}
        for k in ("precision", "recall", "f1", "owner_accuracy", "status_accuracy",
                  "deadline_exact_accuracy", f"deadline_within_{DEADLINE_TOLERANCE_DAYS}d_accuracy"):
            vals = [r[k] for r in per_run if r[k] is not None]
            agg[k] = round(stats.mean(vals), 3) if vals else None
        agg["validation_failures"] = sum(r["validation_failures"].get(name, 0) for r in runs)
        agg["api_failures"] = agg_api_failures
        # Denominator excludes requests that never completed - see parse_run.
        agg["parses"] = len(runs) * len(annotations) - agg_api_failures
        agg["n_runs"] = len(runs)
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
        runs = runs_with(cache, cond)
        if not runs:
            continue
        oc = ot = sc = st_ = dc = dt = 0
        for run in runs:
            for blk in scorable(run["conditions"][cond]):
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


def deadline_offsets(cache: dict, annotations: list[dict]) -> dict:
    """Distribution of (predicted deadline - true deadline) in days, per condition.

    Exact-match accuracy alone cannot tell a model that is *randomly* wrong about dates from one
    that is *systematically* wrong, and the two mean very different things. A random miss is a
    comprehension limit; a constant offset is a resolution bug that a prompt could plausibly fix,
    and it would silently shift every reminder this product sends.
    """
    by_file = {e["transcript_file"]: e for e in annotations}
    out = {}
    for cond in CONDITIONS:
        runs = runs_with(cache, cond)
        if not runs:
            continue
        counts: dict = {}
        total = 0
        for run in runs:
            for blk in scorable(run["conditions"][cond]):
                exp = by_file[blk["transcript_file"]]["expected_action_items"]
                pred = blk["predicted"]
                for ei, pi, _ in _match_overlap(exp, pred):
                    exp_dl = _parse_date(exp[ei]["deadline"])
                    if exp_dl is None:
                        continue
                    total += 1
                    pred_dl = _parse_date(pred[pi].get("deadline"))
                    key = "none" if pred_dl is None else (pred_dl - exp_dl).days
                    counts[key] = counts.get(key, 0) + 1
        if not total:
            continue
        # The single most common wrong offset, and how much of the error it accounts for.
        wrong = {k: v for k, v in counts.items() if k != 0}
        top = max(wrong.items(), key=lambda kv: kv[1]) if wrong else None
        out[cond] = {
            "total": total,
            "exact": counts.get(0, 0),
            "counts": counts,
            "dominant_offset": top[0] if top else None,
            "dominant_share": round(top[1] / total, 3) if top else None,
        }
    return out


def completeness(cache: dict) -> dict:
    """Record-quality metrics, computed from the cached predictions alone (no model calls).

    Extraction F1 asks "did it find the tasks". These ask "are the records it produced actually
    usable" - which is what the guidance is written to control. The implemented guidance tells the
    model who counts as an owner, how to resolve a date, to give a confidence reflecting how
    explicit the transcript was, and what source_decision is for. None of that shows up in F1.
    """
    out = {}
    for cond in CONDITIONS:
        runs = runs_with(cache, cond)
        if not runs:
            continue
        total = src = owner_set = 0
        confs: list[float] = []
        for run in runs:
            for blk in scorable(run["conditions"][cond]):
                for pred in blk["predicted"]:
                    total += 1
                    if pred.get("source_decision"):
                        src += 1
                    if pred.get("owner"):
                        owner_set += 1
                    if pred.get("confidence") is not None:
                        confs.append(float(pred["confidence"]))
        fails = sum(r["validation_failures"].get(cond, 0) for r in runs)
        parses = sum(len(scorable(r["conditions"][cond])) for r in runs)
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


CONFIDENCE_BUCKETS = [(0.0, 0.80), (0.80, 0.90), (0.90, 0.95), (0.95, 0.99), (0.99, 1.01)]


def confidence_calibration(cache: dict, annotations: list[dict], cond: str = "prod") -> dict:
    """Does a higher confidence score actually mean the item is more likely to be real?

    The score is displayed on every card, so it is worth knowing whether it carries
    information. There is no annotated confidence to compare against - the ground truth
    records description, owner, deadline and status only - so correctness is taken from the
    same overlap matcher used everywhere else: a prediction that matches an annotated item is
    real, one that matches nothing is spurious.

    Two properties are distinguished, because they are not the same thing. *Calibration* asks
    whether 0.9 means right nine times in ten. *Discrimination* asks only whether lower scores
    are more often wrong. A review flag needs the second; only a probability needs the first.
    """
    by_file = {e["transcript_file"]: e for e in annotations}
    hits: list[float] = []
    misses: list[float] = []
    for run in runs_with(cache, cond):
        for blk in scorable(run["conditions"][cond]):
            expected = by_file[blk["transcript_file"]]["expected_action_items"]
            predicted = blk["predicted"]
            matched = {pi for _, pi, _ in _match_overlap(expected, predicted)}
            for i, pred in enumerate(predicted):
                c = pred.get("confidence")
                if c is not None:
                    (hits if i in matched else misses).append(float(c))
    if not hits and not misses:
        return {}

    buckets = []
    for lo, hi in CONFIDENCE_BUCKETS:
        h = sum(1 for c in hits if lo <= c < hi)
        m = sum(1 for c in misses if lo <= c < hi)
        if h + m:
            buckets.append({"lo": lo, "hi": hi, "n": h + m, "matched_rate": round(h / (h + m), 3)})
    return {
        "condition": cond,
        "matched": {"n": len(hits), "mean": round(sum(hits) / len(hits), 3) if hits else None},
        "spurious": {"n": len(misses),
                     "mean": round(sum(misses) / len(misses), 3) if misses else None},
        "buckets": buckets,
    }


def _models_by_name(sets: dict) -> dict:
    """Model name -> the model id(s) recorded in the cached runs of every set."""
    seen: dict[str, set] = {}
    for cache, _ in sets.values():
        for run in cache.get("runs", []):
            for cond, model in (run.get("models") or {}).items():
                if cond in CONDITIONS and model:
                    seen.setdefault(CONDITIONS[cond].short, set()).add(model)
    return {name: ", ".join(sorted(ids)) for name, ids in sorted(seen.items())}

# Operational facts that do not come out of the scores but decide deployability. Kept beside the
# numbers deliberately: where the accuracy columns are close, price is what separates the options.
_MODEL_NOTES = {
    "prod": "~$3 / $15 per M tokens",
    "haiku_prod": "~$1 / $5 per M tokens",
    "gemini_prod": "~$0.30 / $2.50 per M tokens",
}

# Mirrors LOW_CONFIDENCE in frontend/src/lib/format.ts: below it, a card asks for review.
REVIEW_THRESHOLD = 0.85

SET_LABELS = {"short": "Short", "long": "Long", "all": "All eight"}


# ------------------------------------------------------------------- statistics
def permutation_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """Exact two-sample permutation test on the difference of means.

    Every split of the pooled per-run values into groups of the original sizes is enumerated
    (12,870 for eight runs against eight), so the p-value is exact rather than sampled.
    Returns (mean(a) - mean(b), two-sided p).
    """
    pool, n = a + b, len(a)
    observed = abs(stats.mean(a) - stats.mean(b))
    hits = total = 0
    for idx in itertools.combinations(range(len(pool)), n):
        chosen = set(idx)
        x = [pool[i] for i in chosen]
        y = [pool[i] for i in range(len(pool)) if i not in chosen]
        total += 1
        hits += abs(stats.mean(x) - stats.mean(y)) >= observed - 1e-12
    return round(stats.mean(a) - stats.mean(b), 3), round(hits / total, 4)


TESTED_PAIRS = [("gemini_prod", "prod"), ("gemini_prod", "haiku_prod"), ("prod", "haiku_prod"),
                ("prod", "naive"), ("gemini_prod", "gemini_naive")]


def pair_tests(overlap: dict) -> dict:
    """Permutation tests on per-run precision, recall and F1 for each compared pair."""
    out = {}
    for x, y in TESTED_PAIRS:
        if x in overlap and y in overlap:
            out[f"{x}|{y}"] = {
                m: permutation_test([r[m] for r in overlap[x]["runs"]],
                                    [r[m] for r in overlap[y]["runs"]])
                for m in ("precision", "recall", "f1")}
    return out


def merge_caches(*caches: dict) -> dict:
    """Join run i of each cache into one run, per condition, so the sets can be scored together.

    Runs are independent samples, so pairing them by position introduces nothing; it only lets
    one precision / recall / F1 be computed per run over every transcript at once.
    """
    out = {"runs": []}
    for cond in CONDITIONS:
        parts = [runs_with(c, cond) for c in caches]
        for group in zip(*parts):
            out["runs"].append({
                "conditions": {cond: [b for r in group for b in r["conditions"][cond]]},
                "validation_failures": {cond: sum(r["validation_failures"].get(cond, 0)
                                                  for r in group)},
                "api_failures": {cond: sum(r.get("api_failures", {}).get(cond, 0)
                                           for r in group)},
                "models": {cond: group[0].get("models", {}).get(cond)},
            })
    return out


def recall_by_status(cache: dict, annotations: list[dict], cond: str) -> dict:
    """Share of annotated items found, split by the item's annotated status."""
    by_file = {e["transcript_file"]: e for e in annotations}
    found: dict = {}
    for run in runs_with(cache, cond):
        for blk in scorable(run["conditions"][cond]):
            items = by_file[blk["transcript_file"]]["expected_action_items"]
            hit = {ei for ei, _, _ in _match_overlap(items, blk["predicted"])}
            for i, item in enumerate(items):
                h, t = found.get(item["status"], (0, 0))
                found[item["status"]] = (h + (i in hit), t + 1)
    return found


def empty_responses(cache: dict, cond: str) -> int:
    """Responses that passed validation but contained no action items at all.

    A validation failure also leaves an empty block, so those are subtracted per run.
    """
    n = 0
    for run in runs_with(cache, cond):
        empty = sum(1 for b in scorable(run["conditions"][cond]) if not b["predicted"])
        n += max(0, empty - run["validation_failures"].get(cond, 0))
    return n


def below_threshold(cache: dict, annotations: list[dict], cond: str) -> tuple[int, int]:
    """(real, spurious) counts of predictions scored below REVIEW_THRESHOLD."""
    by_file = {e["transcript_file"]: e for e in annotations}
    real = spurious = 0
    for run in runs_with(cache, cond):
        for blk in scorable(run["conditions"][cond]):
            items = by_file[blk["transcript_file"]]["expected_action_items"]
            hit = {pi for _, pi, _ in _match_overlap(items, blk["predicted"])}
            for i, p in enumerate(blk["predicted"]):
                c = p.get("confidence")
                if c is not None and c < REVIEW_THRESHOLD:
                    real += i in hit
                    spurious += i not in hit
    return real, spurious


def transcript_profile(directory: Path, annotations: list[dict]) -> dict:
    """Word counts and attendee counts, read from the transcript files themselves."""
    words, people = [], []
    for e in annotations:
        text = (directory / e["transcript_file"]).read_text()
        words.append(len(text.split()))
        line = next((ln for ln in text.splitlines() if ln.startswith("Attendees:")), "")
        people.append(line.count("("))
    return {"transcripts": len(annotations), "words": (min(words), max(words)),
            "people": (min(people), max(people)),
            "items": sum(len(e["expected_action_items"]) for e in annotations)}


def build_results(sets: dict) -> dict:
    """Everything the two documents report, computed once from the cached predictions."""
    out = {}
    for name, (cache, ann) in sets.items():
        ov = aggregate(cache, ann, "overlap")
        out[name] = {
            "overlap": ov,
            "tests": pair_tests(ov),
            "completeness": completeness(cache),
            "offsets": deadline_offsets(cache, ann),
            "counts": pooled_field_counts(cache, ann),
            "status_recall": {c: recall_by_status(cache, ann, c) for c in ov},
            "empty": {c: empty_responses(cache, c) for c in ov},
            "below_threshold": {c: below_threshold(cache, ann, c) for c in ov},
            "confidence": {c: confidence_calibration(cache, ann, c)
                           for c in ("gemini_prod", "prod") if c in ov},
        }
    return out


# ------------------------------------------------------------------- formatting
def _wrap(text: str, indent: str = "", width: int = 96) -> str:
    """Re-flow a generated paragraph so the markdown source stays readable in a diff."""
    return "\n\n".join(
        textwrap.fill(" ".join(para.split()), width=width, subsequent_indent=indent)
        for para in text.split("\n\n"))


def _pct(value) -> str:
    return "-" if value is None else f"{value:.0%}"


def _p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def _gap(test: tuple[float, float]) -> str:
    d, p = test
    return f"{d:+.3f}, {_p(p)}"


def _standing(test: tuple[float, float], alpha: float = 0.05) -> str:
    """'ahead' / 'behind' / 'level' - the verdict a difference supports, not just its sign."""
    d, p = test
    if p >= alpha:
        return "level"
    return "ahead" if d > 0 else "behind"


def _frac(pair) -> str:
    h, t = pair
    return f"{h}/{t} ({h / t:.0%})" if t else "-"


def _offset_shape(entry: dict) -> str:
    dom = entry["dominant_offset"]
    if dom is None:
        return "no errors"
    if dom == "none":
        return f"left blank ({entry['dominant_share']:.0%})"
    return f"{dom:+d} day ({entry['dominant_share']:.0%})"


def _profile_row(name: str, prof: dict, role: str) -> str:
    w, p = prof["words"], prof["people"]
    people = str(p[0]) if p[0] == p[1] else f"{p[0]}-{p[1]}"
    return (f"| {SET_LABELS[name]} | {prof['transcripts']} | {w[0]:,}-{w[1]:,} | "
            f"{people} | {prof['items']} | {role} |")


_ROLES = {"short": "Development: the prompt was refined against it",
          "long": "Held out: written after the prompt was fixed, never used to tune it"}


def _decision(res: dict) -> str:
    """The decision paragraph. Each clause is derived from a test, so it cannot overstate."""
    parts = []
    for name in ("short", "long", "all"):
        t = res[name]["tests"].get("gemini_prod|prod")
        if not t:
            continue
        where = {"short": "on the short set", "long": "on the long set",
                 "all": "across all eight transcripts"}[name]
        parts.append(f"{_standing(t['f1'])} {where} ({_gap(t['f1'])})")
    never_behind = all(_standing(res[n]["tests"]["gemini_prod|prod"]["f1"]) != "behind"
                       for n in ("short", "long", "all") if "gemini_prod|prod" in res[n]["tests"])
    lead = ("It is never significantly behind Claude Sonnet on F1: " if never_behind
            else "Against Claude Sonnet on F1 it is ")
    body = lead + ", ".join(parts[:-1]) + ", and " + parts[-1] + "."
    lp = res["long"]["tests"].get("gemini_prod|prod", {}).get("precision")
    if lp and _standing(lp) == "ahead":
        body += (f" On the long set it is also more precise ({_gap(lp)}), so it proposes fewer "
                 f"items that are not real tasks.")
    body += (" It also costs a tenth of Claude Sonnet's price per input token and a sixth per "
             "output token.")
    haiku = [(n, res[n]["offsets"].get("haiku_prod")) for n in ("short", "long")]
    shares = [f"{o['dominant_share']:.0%}" + (" of its matched deadlines" if i == 0 else "")
              + f" on the {n} set"
              for i, (n, o) in enumerate((n, o) for n, o in haiku
                                         if o and o["dominant_offset"] == 1)]
    if shares:
        body += (" Claude Haiku is rejected because it resolves deadlines one day late: "
                 "exactly +1 day on " + " and ".join(shares) + ".")
    return body


def _completed_work(res: dict) -> str:
    sr = res["all"]["status_recall"]
    if "gemini_prod" not in sr or "prod" not in sr or "done" not in sr["prod"]:
        return ""
    g, c = sr["gemini_prod"], sr["prod"]
    rate = lambda d, s: d[s][0] / d[s][1]  # noqa: E731
    return _wrap(
        f"**Much of Claude Sonnet's gap is completed work.** The answer keys include work the "
        f"meeting reports as already finished (status `done`), because the board records it. "
        f"Across all eight transcripts Claude Sonnet finds {rate(c, 'done'):.0%} of those "
        f"items against Gemini Flash's {rate(g, 'done'):.0%}, while on open work the two are "
        f"close ({rate(c, 'todo'):.0%} against {rate(g, 'todo'):.0%} of to-do items, "
        f"{rate(c, 'in_progress'):.0%} against {rate(g, 'in_progress'):.0%} of in-progress "
        f"ones). Claude Haiku finds {rate(sr['haiku_prod'], 'done'):.0%} of completed items.")


def _empty_note(res: dict) -> str:
    n = res["all"]["empty"].get("prod", 0)
    if not n:
        return ""
    times = "once" if n == 1 else f"{n} times"
    g = res["all"]["empty"].get("gemini_prod", 0)
    other = ("Gemini Flash never did." if not g
             else f"Gemini Flash did so {g} time{'s' if g > 1 else ''}.")
    return _wrap(
        f"Claude Sonnet also returned a valid response containing no action items {times}. The "
        f"application would show that meeting as processed with an empty board, which is harder "
        f"to notice than a failed parse. {other}")


def render_report(res: dict, profiles: dict) -> str:
    """The short report: decision, the two test sets, and two tables."""
    today = date.today().isoformat()
    a = res["all"]
    rows = []
    for cond in COMPARISON_CONDITIONS:
        if cond not in a["overlap"]:
            continue
        o = a["offsets"].get(cond, {})
        b = "**" if cond == "gemini_prod" else ""
        f1 = [res[n]["overlap"][cond]["f1"] for n in ("short", "long", "all")]
        rows.append(
            f"| {b}{CONDITIONS[cond].short}{b} | {f1[0]} | {f1[1]} | {b}{f1[2]}{b} | "
            f"{a['overlap'][cond]['precision']} | {a['overlap'][cond]['recall']} | "
            f"{o['exact'] / o['total']:.0%} | {_MODEL_NOTES[cond]} |")

    g_rows = []
    for base, impr in (("gemini_naive", "gemini_prod"), ("naive", "prod")):
        mb, mi = a["overlap"][base], a["overlap"][impr]
        qb, qi = a["completeness"][base], a["completeness"][impr]
        t = a["tests"][f"{impr}|{base}"]["f1"]
        g_rows.append(
            f"| {CONDITIONS[impr].short} | {mb['validation_failures']}/{mb['parses']} -> "
            f"**{mi['validation_failures']}/{mi['parses']}** | "
            f"{_pct(qb['source_decision_rate'])} -> **{_pct(qi['source_decision_rate'])}** | "
            f"{mb['f1']} -> **{mi['f1']}** ({_p(t[1])}) |")

    verdicts = {CONDITIONS[i].short: _standing(a["tests"][f"{i}|{b}"]["f1"])
                for b, i in (("gemini_naive", "gemini_prod"), ("naive", "prod"))}
    raised = [m for m, v in verdicts.items() if v == "ahead"]
    if len(raised) == 2:
        guidance_f1 = "Across all eight transcripts the F1 gain is significant on both models."
    elif raised:
        guidance_f1 = (f"Across all eight transcripts the F1 gain is significant on {raised[0]} "
                       f"only.")
    else:
        guidance_f1 = "The F1 difference is not separable from run-to-run noise."
    g_real, g_spur = a["below_threshold"].get("gemini_prod", (0, 0))
    c_real, c_spur = a["below_threshold"].get("prod", (0, 0))

    return f"""# Evaluation Report

_Generated by `python -m eval.run_eval --write-report` on {today}._
_Method, per-condition figures and caveats: [evaluation-appendix.md](evaluation-appendix.md).
Speech-to-text: [asr-evaluation.md](asr-evaluation.md). Subtask generation:
[subtask-evaluation-report.md](subtask-evaluation-report.md)._

## Decision

{_wrap("**Extraction runs on Gemini Flash.** " + _decision(res))}

## Test sets

| Set | Transcripts | Words each | People each | Annotated action items | Role |
|---|---|---|---|---|---|
{_profile_row("short", profiles["short"], _ROLES["short"])}
{_profile_row("long", profiles["long"], _ROLES["long"])}

{_wrap('''All eight are synthetic SAP programme meetings. Every configuration was run eight
times on each set. Differences are tested with an exact permutation test over the eight per-run
scores, and a difference is only called a lead when p < 0.05.''')}

## Step 1 - choosing the model

Every row uses the with-guidance configuration the application runs; only the model changes.

| Model | F1 short | F1 long | F1 all eight | Precision | Recall | Deadlines exact | Cost |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

_Precision, recall and deadlines are over all eight transcripts._

{_completed_work(res)}

{_empty_note(res)}

{_wrap('''The three models differ in price tier and release date, and the difference runs both
ways: Claude Sonnet is a larger tier, Gemini Flash a later release. This is a decision for this
project, not a ranking of vendors.''')}

## Step 2 - what the prompt and schema guidance adds

Each model was also run without the guidance: a one-line prompt and a schema with the field
descriptions removed. The output format is identical; only the guidance text differs. All eight
transcripts:

| Model | Responses failing validation | Source decision filled | F1 |
|---|---|---|---|
{chr(10).join(g_rows)}

{_wrap(f'''Without guidance both models sometimes return output that fails validation, and the
application then gets no tasks at all; with guidance that never happened. With guidance both
models also record which decision each task came from. {guidance_f1}''')}

## What this does not show

{_wrap(f'''- **The meetings are synthetic.** They are written text, not recorded speech. The long
transcripts and their answer keys were drafted with an AI assistant (Claude). Text written by one
candidate's model family could suit that family; here it would favour Claude Sonnet, which is the
opposite direction to the decision.''', indent="  ")}
{_wrap(f'''- **Eight meetings is still a small sample.** The results show the choice holds on
longer, harder meetings than the ones the prompt was built on; they do not show it holds for
every kind of meeting.''', indent="  ")}
{_wrap(f'''- **The low-confidence review flag was tuned on Claude Sonnet.** Every Sonnet item
scored below {REVIEW_THRESHOLD} was wrong ({c_spur} of {c_real + c_spur}), but Gemini Flash
never scored an item below {REVIEW_THRESHOLD} ({g_real + g_spur} items in all runs), so on the
implemented model the flag does not fire. See the appendix.''', indent="  ")}
"""


def _set_table(res: dict, conds: list[str]) -> list[str]:
    rows = []
    for cond in conds:
        for name in ("short", "long", "all"):
            m = res[name]["overlap"].get(cond)
            if not m:
                continue
            c = res[name]["counts"][cond]
            rows.append(
                f"| {CONDITIONS[cond].short} | {SET_LABELS[name]} | {m['n_runs']} | "
                f"{m['precision']} | {m['recall']} | **{m['f1']}** | "
                f"{m['validation_failures']}/{m['parses']} | {_frac(c['owner'])} | "
                f"{_frac(c['status'])} |")
    return rows


def _confidence_rows(cal: dict) -> str:
    return "\n".join(f"| {b['lo']:.2f} - {min(b['hi'], 1.0):.2f} | {b['n']} | "
                     f"{b['matched_rate']:.0%} |" for b in cal["buckets"])


def render_appendix(res: dict, profiles: dict, models: dict, judge_note: str) -> str:
    """The technical appendix: method, every condition on every set, and the limitations."""
    today = date.today().isoformat()
    a = res["all"]

    # Study 1 - guidance, per model and set.
    s1 = []
    for base, impr in (("gemini_naive", "gemini_prod"), ("naive", "prod")):
        for name in ("short", "long", "all"):
            mb, mi = res[name]["overlap"][base], res[name]["overlap"][impr]
            qb, qi = res[name]["completeness"][base], res[name]["completeness"][impr]
            t = res[name]["tests"][f"{impr}|{base}"]
            s1.append(
                f"| {CONDITIONS[impr].short} | {SET_LABELS[name]} | "
                f"{mb['validation_failures']}/{mb['parses']} -> "
                f"**{mi['validation_failures']}/{mi['parses']}** | "
                f"{_pct(qb['source_decision_rate'])} -> **{_pct(qi['source_decision_rate'])}** | "
                f"{mb['recall']} -> **{mi['recall']}** | {mb['f1']} -> **{mi['f1']}** | "
                f"{_gap(t['f1'])} |")
    pairs = {"Gemini Flash": ("gemini_naive", "gemini_prod"), "Claude Sonnet": ("naive", "prod")}
    raised, details = [], []
    for m, (b, i) in pairs.items():
        v = {n: _standing(res[n]["tests"][f"{i}|{b}"]["f1"]) for n in ("short", "long", "all")}
        if v["all"] == "ahead":
            raised.append(m)
        sig = [n for n in ("short", "long") if v[n] == "ahead"]
        if len(sig) == 2:
            details.append(f"{m}'s gain is significant on both sets")
        elif sig:
            other = "long" if sig[0] == "short" else "short"
            details.append(f"{m}'s gain is significant on the {sig[0]} set but not the {other}")
        else:
            details.append(f"{m}'s gain is not significant on either set alone")
    if len(raised) == 2:
        gain_text = "Across all eight transcripts the guidance raises F1 significantly on both models."
    elif raised:
        gain_text = f"Across all eight transcripts the guidance raises F1 significantly on {raised[0]} only."
    else:
        gain_text = "Across all eight transcripts the F1 difference is not separable from noise."
    gain_text += " Within a single set, " + "; ".join(details) + "."
    fail_sets = [f"{CONDITIONS[b].short} on the {SET_LABELS[n].lower()} set "
                 f"({res[n]['overlap'][b]['validation_failures']}/{res[n]['overlap'][b]['parses']})"
                 for b in ("gemini_naive", "naive") for n in ("short", "long")
                 if res[n]["overlap"][b]["validation_failures"]]
    with_fails = sum(res["all"]["overlap"][i]["validation_failures"] for i in ("gemini_prod", "prod"))
    with_parses = sum(res["all"]["overlap"][i]["parses"] for i in ("gemini_prod", "prod"))
    src = {CONDITIONS[b].short: _pct(res["all"]["completeness"][b]["source_decision_rate"])
           for b in ("gemini_naive", "naive")}

    # Study 2 - pairwise tests.
    s2_tests = []
    for key, label in (("gemini_prod|prod", "Gemini Flash - Claude Sonnet"),
                       ("gemini_prod|haiku_prod", "Gemini Flash - Claude Haiku"),
                       ("prod|haiku_prod", "Claude Sonnet - Claude Haiku")):
        for name in ("short", "long", "all"):
            t = res[name]["tests"].get(key)
            if t:
                s2_tests.append(f"| {label} | {SET_LABELS[name]} | {_gap(t['precision'])} | "
                                f"{_gap(t['recall'])} | {_gap(t['f1'])} |")

    # Recall by status.
    status_rows = []
    for cond in COMPARISON_CONDITIONS:
        sr = a["status_recall"][cond]
        status_rows.append(f"| {CONDITIONS[cond].short} | {_frac(sr['todo'])} | "
                           f"{_frac(sr['in_progress'])} | {_frac(sr['done'])} |")

    # Deadlines.
    dl_rows = []
    for cond in COMPARISON_CONDITIONS + ["naive"]:
        for name in ("short", "long"):
            o = res[name]["offsets"].get(cond)
            if o:
                dl_rows.append(f"| {CONDITIONS[cond].label} | {SET_LABELS[name]} | "
                               f"{o['exact']}/{o['total']} ({o['exact'] / o['total']:.0%}) | "
                               f"{_offset_shape(o)} |")
    hk = [res[n]["offsets"]["haiku_prod"] for n in ("short", "long")]
    plus_one_elsewhere = sum(res[n]["offsets"][c]["counts"].get(1, 0)
                             for n in ("short", "long") for c in ("prod", "gemini_prod"))
    others = ("No other with-guidance configuration produces a +1 day error even once."
              if not plus_one_elsewhere else
              f"The other with-guidance configurations produce it {plus_one_elsewhere} times in "
              f"total.")
    nv = res["long"]["offsets"].get("naive", {})
    naive_note = ""
    if nv.get("dominant_offset") == 1 and not res["long"]["offsets"]["prod"]["counts"].get(1):
        naive_note = (f" Claude Sonnet without guidance shows the same +1 day drift on the long "
                      f"set ({nv['dominant_share']:.0%}), which the guidance removes.")

    # Confidence.
    conf_blocks = []
    for cond in ("gemini_prod", "prod"):
        cal = a["confidence"].get(cond)
        if not cal:
            continue
        real, spur = a["below_threshold"][cond]
        conf_blocks.append(f"""**{CONDITIONS[cond].short}** - real items average {cal['matched']['mean']}
(n={cal['matched']['n']}), spurious ones {cal['spurious']['mean']} (n={cal['spurious']['n']}).
Below {REVIEW_THRESHOLD}: {real} real, {spur} spurious.

| Confidence | Items | Real |
|---|---|---|
{_confidence_rows(cal)}
""")
    g_below = sum(a["below_threshold"]["gemini_prod"])

    long_p, short_p = profiles["long"], profiles["short"]
    return f"""# Evaluation Report - Technical Appendix

_Generated by `python -m eval.run_eval --write-report` on {today}. Re-run to refresh._
_Summary and decision: [evaluation-report.md](evaluation-report.md). Speech-to-text:
[asr-evaluation.md](asr-evaluation.md). Subtask generation:
[subtask-evaluation-report.md](subtask-evaluation-report.md)._

## Test sets and method

| Set | Transcripts | Words each | People each | Annotated action items | Role |
|---|---|---|---|---|---|
{_profile_row("short", short_p, _ROLES["short"])}
{_profile_row("long", long_p, _ROLES["long"])}

- **Short set:** `data/synthetic-transcripts/`, answer key `data/annotated-test-set/annotations.json`.
- **Long set:** `data/synthetic-transcripts-long/`, answer key
  `data/annotated-test-set-long/annotations.json`. Each long transcript was written to include
  deadlines revised later in the meeting, a task handed from one person to another, an owner
  who is not in the meeting, work owned by a team rather than a person, and requests that are
  later cancelled, parked or rejected. The answer key lists those non-tasks separately
  (`not_action_items`) so it is clear what was deliberately left out.
- The answer keys count work reported as already finished as a task with status `done`,
  because the board records it.
- Each transcript is parsed with its true meeting date, so relative cues ("by Friday") resolve
  to one correct date.
- Predictions are matched one-to-one to annotated items by **word overlap** (Jaccard over
  content words, threshold {MATCH_THRESHOLD}), with no model involved, so scoring is
  repeatable. Owner, status and deadline are then scored on matched pairs only.
- **Precision** = matched / predicted, **recall** = matched / annotated, **F1** is their
  harmonic mean. One value of each is computed per run over every transcript in the set.
- Every configuration was run **8 times on each set**. "All eight" joins run *i* of the short
  set with run *i* of the long set; runs are independent, so this pairing adds nothing but lets
  one score cover all eight transcripts.
- Differences use an **exact permutation test** over the per-run scores: all 12,870 ways of
  splitting sixteen runs into two groups of eight are enumerated. A difference is called a lead
  only when p < 0.05.
- Requests that never completed (rate limit, capacity) are excluded as API failures. Only
  responses that arrived and failed the schema count as validation failures.

{judge_note}

Models: {", ".join(f"{k} `{v}`" for k, v in models.items())}.

## Study 1 - does the guidance help?

Within each model the two configurations differ only in guidance text; the output schema is
identical (`eval/test_matching.py`, `eval/test_providers.py`). Each cell reads *without
guidance* -> **with guidance**. The last column tests the F1 difference.

| Model | Set | Validation failures | `source_decision` | Recall | F1 | F1 gain |
|---|---|---|---|---|---|---|
{chr(10).join(s1)}

{_wrap(f'''**Reliability.** With guidance neither model ever returned output that failed
validation ({with_fails} of {with_parses} responses). Without it, failures occurred for
{"; ".join(fail_sets)}.

**Accuracy.** {gain_text}

**Record quality.** With guidance both models fill `source_decision` on every item. Without it,
Gemini Flash fills it on {src["Gemini Flash"]} of items and Claude Sonnet on
{src["Claude Sonnet"]}.''')}

## Study 2 - which model?

Every row uses the with-guidance configuration. Owner and status accuracy are over matched items.

| Model | Set | Runs | Precision | Recall | F1 | Validation failures | Owner | Status |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(_set_table(res, COMPARISON_CONDITIONS))}

Differences (first model minus second), with exact permutation p-values:

| Comparison | Set | Precision | Recall | F1 |
|---|---|---|---|---|
{chr(10).join(s2_tests)}

### Which items each model misses (all eight transcripts)

| Model | To do | In progress | Done |
|---|---|---|---|
{chr(10).join(status_rows)}

{_completed_work(res)}

{_empty_note(res)}

## Deadline errors

A model that is wrong by a constant amount has a resolution bug, which shifts every reminder;
one that is randomly wrong has a comprehension limit. The table separates the two.

| Configuration | Set | Exact | Most common error |
|---|---|---|---|
{chr(10).join(dl_rows)}

{_wrap(f'''**Claude Haiku is systematically one day late**: {hk[0]['dominant_share']:.0%} of its
matched deadlines on the short set and {hk[1]['dominant_share']:.0%} on the long set are exactly
+1 day, so every reminder it scheduled would be sent a day late. {others}{naive_note}''')}

## Is the confidence score meaningful?

Every item carries a confidence score and the card flags items below {REVIEW_THRESHOLD} for
review. "Real" means the item matched an annotated one. All eight transcripts:

{chr(10).join(conf_blocks)}
{_wrap(f'''Neither model's score is a calibrated probability. Claude Sonnet's discriminates at the
low end: its items below {REVIEW_THRESHOLD} were all spurious, which is what the {REVIEW_THRESHOLD}
threshold was set from. Gemini Flash, the implemented model, never scored an item below
{REVIEW_THRESHOLD} ({g_below} items), and its spurious items score almost as high as its real
ones. On the implemented model the review flag therefore does not fire, and the score carries
little information. Gemini Flash also produces few spurious items, so the practical cost is
small, but the flag should not be described as a safeguard for this model.''')}

## Limitations

- **Synthetic meetings.** All eight are written text, not recorded speech. The pipeline was
  also run end to end on a real AMI recording, which is not part of the scored sets.
- **Who wrote the long set.** The long transcripts and their answer keys were drafted with an AI
  assistant (Claude). Text from one candidate's model family could suit that family; here it
  would favour Claude Sonnet, the opposite direction to the decision.
- **One annotator.** Each answer key has a single labeller, so there is no agreement measure.
- **Word-overlap matching** occasionally pairs the wrong items when two tasks share many words
  (for example "remove the conflicts" and "review the mitigating controls for the conflicts");
  those pairs show up as large deadline errors. They are rare and do not change any verdict.
- **Eight meetings.** The long set shows the choice holds on harder meetings than the prompt was
  built on; it does not show it holds for every kind of meeting.
- **Models differ in tier and release date**, in both directions, so this is a decision for this
  project rather than a ranking of vendors.
- `gemini-3.7-flash` returned HTTP 503 "high demand" or hung on roughly three attempts in four
  and could not be used; `gemini-3.6-flash` is the newest Flash that answered reliably.
- **A correction worth recording.** An earlier `BARE_TOOL` stripped every key named
  `description`, including the *field* of that name, so the without-guidance configuration
  required a field it did not define. The stripper now removes only annotation text, and
  `eval/test_matching.py` has a regression test. All figures are from runs after the fix.

## Raw results

`eval/results.json` holds every scored metric and test for the short set, the long set and all
eight. `eval/predictions.json` and `eval/predictions_long.json` hold the raw parser output each
run was scored from, so scoring can be repeated without calling any model.
"""

# --------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Evaluate the transcript-parsing pipeline and regenerate the report.")
    ap.add_argument("--parse", action="store_true",
                    help="COSTS API CALLS. Parse the chosen test set once more and append the run "
                         "to its cache.")
    ap.add_argument("--set", choices=sorted(TEST_SETS), default="short", dest="test_set",
                    help="Which test set --parse runs: 'short' (the development set) or 'long' "
                         "(the held-out set). Scoring always covers both. Default: short.")
    ap.add_argument("--provider", choices=GROUPS, default="claude",
                    help="Which model group --parse should run. 'claude' (Sonnet, with and "
                         "without guidance) and 'haiku' spend Anthropic credit; 'gemini' spends "
                         "Gemini credit. Default: claude.")
    ap.add_argument("--runs", type=int, default=1,
                    help="How many parse runs to append (only with --parse).")
    ap.add_argument("--rescore-judge", action="store_true",
                    help="COSTS ANTHROPIC API CALLS. Re-run the LLM-judge matcher on the short "
                         "set. Without this, stored judge scores are reused.")
    ap.add_argument("--write-report", action="store_true",
                    help="Refresh docs/evaluation-report.md and docs/evaluation-appendix.md. "
                         "Free - no API calls.")
    args = ap.parse_args()

    if args.parse:
        tdir, ann_path, cache_path = TEST_SETS[args.test_set]
        annotations = json.loads(ann_path.read_text())
        cache = json.loads(cache_path.read_text()) if cache_path.exists() \
            else {"note": "Cached raw parser output.", "runs": []}
        conds = [k for k, c in CONDITIONS.items() if c.group == args.provider]
        for i in range(args.runs):
            print(f"--- {args.provider} parse run {i + 1}/{args.runs} on the {args.test_set} set "
                  f"(calling the model) ---")
            cache["runs"].append(parse_run(annotations, conds, tdir))
            cache_path.write_text(json.dumps(cache, indent=2, default=str) + "\n")
        print(f"Cached to {cache_path.relative_to(REPO_ROOT)}")

    sets, profiles = {}, {}
    for name, (tdir, ann_path, cache_path) in TEST_SETS.items():
        if not cache_path.exists():
            sys.exit(f"No cached predictions for the {name} set. Run: "
                     f"python -m eval.run_eval --parse --set {name}")
        ann = json.loads(ann_path.read_text())
        sets[name] = (json.loads(cache_path.read_text()), ann)
        profiles[name] = transcript_profile(tdir, ann)
    sets["all"] = (merge_caches(sets["short"][0], sets["long"][0]),
                   sets["short"][1] + sets["long"][1])

    # Word-overlap scoring is pure computation - never touches any API.
    res = build_results(sets)

    # The judge matcher costs one Anthropic call per transcript per condition, so its scores are
    # cached per condition and only ever computed on request. Short set only.
    short_cache, short_ann = sets["short"]
    overlap = res["short"]["overlap"]
    stored = json.loads(RESULTS_JSON.read_text()) if RESULTS_JSON.exists() else {}
    stored_judge = stored.get("judge", {})
    judge, need = {}, []
    for name in overlap:
        prev = stored_judge.get(name)
        prev_n = len(prev.get("runs", [])) if prev else None
        if prev and not args.rescore_judge and prev_n == overlap[name]["n_runs"]:
            judge[name] = prev
        else:
            need.append(name)
    if need and args.rescore_judge:
        print(f"Running the LLM judge on {need} - THIS CALLS THE ANTHROPIC API.")
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        judge.update(aggregate(short_cache, short_ann, "judge", client, only=need))

    for name in ("short", "long", "all"):
        print(f"\n=== {SET_LABELS[name]} ===")
        hdr = f"{'condition':34} {'runs':>5} {'prec':>7} {'recall':>7} {'F1':>7} {'fail':>8}"
        print(hdr)
        print("-" * len(hdr))
        for cond, agg in res[name]["overlap"].items():
            print(f"{LABELS[cond]:34} {agg['n_runs']:5} {agg['precision']:7} {agg['recall']:7} "
                  f"{agg['f1']:7} {str(agg['validation_failures']) + '/' + str(agg['parses']):>8}")
        t = res[name]["tests"].get("gemini_prod|prod", {}).get("f1")
        if t:
            print(f"Gemini Flash - Claude Sonnet, F1: {_gap(t)}")

    RESULTS_JSON.write_text(json.dumps(
        {"sets": {n: {k: v for k, v in r.items()} for n, r in res.items()}, "judge": judge},
        indent=2, default=str) + "\n")
    print(f"\nWrote {RESULTS_JSON.relative_to(REPO_ROOT)}")

    if args.write_report:
        if judge:
            judge_note = _wrap(
                "A semantic LLM-judge matcher was run on the short set for: "
                + "; ".join(f"{LABELS[c]} F1 {judge[c]['f1']}" for c in judge) + ".")
        else:
            judge_note = _wrap("A semantic LLM-judge matcher is available (`--rescore-judge`) but "
                               "has not been run, so every figure uses word overlap.")
        models = _models_by_name(sets)
        REPORT_MD.write_text(render_report(res, profiles))
        APPENDIX_MD.write_text(render_appendix(res, profiles, models, judge_note))
        print(f"Wrote {REPORT_MD.relative_to(REPO_ROOT)} and "
              f"{APPENDIX_MD.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
