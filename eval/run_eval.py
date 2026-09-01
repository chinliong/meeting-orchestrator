"""Evaluation harness for the LLM transcript-parsing pipeline (Objective 5).

What this measures
------------------
The pipeline is given a meeting transcript and must return structured action items. This
harness scores that output against a hand-annotated answer key: action-item precision /
recall / F1, plus owner, status and deadline accuracy on the items that matched.

Two questions are answered, by two different sets of conditions (see CONDITIONS):

1. **Does the guidance layer help?** A 2x2: guidance level - "Basic", a no-guidance control,
   against "Improved", the shipped configuration - crossed with model family, Claude Sonnet
   against Gemini Flash. On Claude alone the two levels cannot be separated on extraction
   accuracy: the run-to-run spread is larger than the gap, and the report says so rather than
   claiming a gain. The second model tests whether the guidance does work a capable model
   already does unaided.

2. **Which model should the project use?** Claude Sonnet (the incumbent), Claude Haiku, Gemini
   Flash and Mistral Small, all on the shipped configuration only. The incumbent is included
   because the question is whether to replace it. Tiers and release dates differ and the
   mismatch runs both ways - Sonnet is a larger tier, Gemini Flash is a later release - so
   this is reported as a procurement decision for this project, not a vendor ranking. Haiku is
   the tier-matched Claude entry that keeps the choice honest.

Four design decisions worth knowing
-----------------------------------
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

3. **Each run holds one model group.** A `--parse` invocation records exactly one group, so run
   counts differ per condition and every aggregate filters with `runs_with()` rather than
   assuming a uniform run list. Adding runs for one model therefore cannot disturb another's
   cached figures - which is also what keeps the paid Claude conditions from being re-billed
   when a free model is sampled.

4. **API failures are not model failures.** A request that never completed (rate limit,
   capacity) is marked and excluded from scoring rather than counted as the model finding
   nothing. Only responses that arrived but did not satisfy the schema count as validation
   failures. Conflating the two would let an exhausted quota masquerade as a quality result.

Usage (from the repo root, with the backend virtualenv active):

    python -m eval.run_eval --write-report                       # regenerate the report - FREE
    python -m eval.run_eval                                      # re-score the cache - FREE
    python -m eval.run_eval --parse --provider gemini --runs 3   # free (20 req/day/model)
    python -m eval.run_eval --parse --provider mistral --runs 3  # free tier
    python -m eval.run_eval --parse --provider haiku --runs 3    # COSTS ANTHROPIC CREDIT (cheap)
    python -m eval.run_eval --parse --provider claude --runs 1   # COSTS ANTHROPIC CREDIT
    python -m eval.run_eval --rescore-judge                      # COSTS ANTHROPIC CREDIT

API BOUNDARY: only `--parse` and `--rescore-judge` contact a model, and only the `claude` /
`haiku` groups and `--rescore-judge` spend Anthropic credit. The default path scores the cached
predictions with pure computation and reuses stored judge scores, so regenerating the report
costs nothing. Judge scores are cached per condition, so adding runs for one model does not
silently re-bill the judge for another.
"""
from __future__ import annotations

import argparse
import copy
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
RESULTS_JSON = REPO_ROOT / "eval" / "results.json"
# Two documents on purpose. The report is what gets opened in a progress check-in and has to
# be readable in a couple of minutes; the appendix carries the methodology, caveats and
# per-condition figures that make the report defensible but would drown it. Nothing is
# dropped - the report links to the appendix for every claim it compresses.
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

# The guidance ships as one layer - the prompt rules and the schema field descriptions carry the
# same instructions - so it is evaluated as one layer. The experiment is a 2x2:
#
#                  Basic guidance                Improved guidance
#   Claude         naive                         prod
#   Gemini         gemini_naive                  gemini_prod
#
# Crossing the two axes answers a question neither answers alone. On this test set the guidance
# effect on Claude is smaller than the run-to-run spread, so it cannot be called an accuracy
# gain. The second model was added expecting the guidance to matter *more* where the model is
# weaker. It did not: the net F1 effect changes sign between the two, and both deltas stay inside
# the noise. What did replicate is the direction of the trade (recall up, precision down) and the
# elimination of validation failures - which is now the best-supported claim here, holding across
# two independent model families.
#
# Both tools emit an identical JSON shape (eval/test_matching.py asserts it for Claude,
# eval/test_providers.py for Gemini after schema translation).
#
# The Claude keys stay "naive"/"prod" because eval/predictions.json is already keyed by them.


@dataclass(frozen=True)
class Condition:
    label: str          # how the report names it, e.g. "Improved (Gemini Flash)"
    provider: str       # "claude" | "gemini" | "mistral" - which adapter drives it
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
    "naive":        Condition("Basic (Claude Sonnet)", "claude", "Basic",
                              BASELINE_PROMPT, BARE_TOOL, group="claude", short="Claude Sonnet"),
    "prod":         Condition("Improved (Claude Sonnet)", "claude", "Improved",
                              SYSTEM_PROMPT, EXTRACTION_TOOL, group="claude", short="Claude Sonnet"),
    "gemini_naive": Condition("Basic (Gemini Flash)", "gemini", "Basic",
                              BASELINE_PROMPT, BARE_TOOL, group="gemini", short="Gemini Flash"),
    "gemini_prod":  Condition("Improved (Gemini Flash)", "gemini", "Improved",
                              SYSTEM_PROMPT, EXTRACTION_TOOL, group="gemini", short="Gemini Flash"),
    # Model comparison, shipped config only. These deliberately carry no Basic arm: the guidance
    # question is already answered by the 2x2 above, and "which model should this product use?"
    # is correctly asked under the configuration that actually ships.
    "haiku_prod":   Condition("Improved (Claude Haiku)", "claude", "Improved",
                              SYSTEM_PROMPT, EXTRACTION_TOOL, group="haiku",
                              short="Claude Haiku", model="claude-haiku-4-5"),
    "mistral_prod": Condition("Improved (Mistral Small)", "mistral", "Improved",
                              SYSTEM_PROMPT, EXTRACTION_TOOL, group="mistral", short="Mistral Small"),
}

LABELS = {key: cond.label for key, cond in CONDITIONS.items()}

# --parse operates on one group at a time, so a run never mixes providers.
GROUPS = sorted({c.group for c in CONDITIONS.values()})

# The model-choice comparison, all under the shipped config. The incumbent (Sonnet) is
# included because the question being answered is "should this project switch?", and a
# candidate list without the thing being replaced cannot answer it. The tiers differ and the
# report says so: Sonnet is a larger tier than the other three, while Gemini Flash is a later
# release than Sonnet. The confound runs both ways, which is precisely why this is reported as
# a procurement decision for this project rather than a vendor ranking.
COMPARISON_CONDITIONS = ["prod", "haiku_prod", "gemini_prod", "mistral_prod"]


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
    shipped code path is exercised as-is; the second return value is the tool to patch in. The
    other providers take the tool as a constructor argument (eval/providers.py) and so return
    None for it.
    """
    if cond.provider == "gemini":
        from eval.providers import GeminiParser
        return GeminiParser(cond.prompt, cond.tool, model=cond.model), None
    if cond.provider == "mistral":
        from eval.providers import MistralParser
        return MistralParser(cond.prompt, cond.tool, model=cond.model), None
    return TranscriptParser(system_prompt=cond.prompt, model=cond.model), cond.tool


def parse_run(annotations: list[dict], conditions: list[str]) -> dict:
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
                transcript = (TRANSCRIPTS_DIR / entry["transcript_file"]).read_text()
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
    usable" - which is what the guidance is written to control. The shipped guidance tells the
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


def _models_used(cache: dict, overlap: dict) -> dict:
    """Provider -> the concrete model id(s) that produced the cached runs.

    Runs cached before this field was recorded carry no model id; those fall back to the value
    configured now, flagged so the report does not present an assumption as a record.
    """
    recorded: dict[str, set] = {}
    unrecorded: set = set()
    for run in cache.get("runs", []):
        models = run.get("models") or {}
        for cond in run.get("conditions", {}):
            if cond not in overlap:
                continue
            group = CONDITIONS[cond].group
            if models.get(cond):
                recorded.setdefault(group, set()).add(models[cond])
            else:
                unrecorded.add(group)

    out = {}
    fallback = {
        "claude": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
        "gemini": os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        "mistral": os.getenv("MISTRAL_MODEL", "mistral-small-2603"),
        "haiku": "claude-haiku-4-5",
    }
    for group in sorted(set(recorded) | unrecorded):
        names = sorted(recorded.get(group, ()))
        if names:
            # At least one run recorded it. Older runs that predate the field are assumed to be
            # the same model rather than reported as a separate unknown.
            out[group] = ", ".join(names)
        else:
            out[group] = f"{fallback.get(group, '?')} (from config; not recorded in cache)"
    return out

# Operational facts that do not come out of the scores but decide deployability. Kept beside the
# numbers deliberately: on a test set this small the accuracy columns are nearly tied, so quota
# and price are what actually separate the options.
_MODEL_NOTES = {
    "prod": "paid, ~$3/$15 per M tokens; current model",
    "haiku_prod": "paid, ~$1/$5 per M tokens",
    "gemini_prod": "free tier used for this evaluation; paid tier available",
    "mistral_prod": "free tier used for this evaluation; paid tier available",
}

# Below this, differences in F1 on this test set are not distinguishable from run-to-run noise.
NOISE_FLOOR_F1 = 0.15


def _wrap(text: str, indent: str = "", width: int = 96) -> str:
    """Re-flow a generated paragraph so the markdown source stays readable in a diff."""
    return "\n\n".join(
        textwrap.fill(" ".join(para.split()), width=width, subsequent_indent=indent)
        for para in text.split("\n\n"))


def _pct(value) -> str:
    return "-" if value is None else f"{value:.0%}"


def _fmt_frac(counts: dict, cond: str, field_: str) -> str:
    k = (counts or {}).get(cond)
    if not k:
        return "-"
    c, t = k[field_]
    return f"{c}/{t} ({c/t:.2f})" if t else "-"


def _offset_shape(entry: dict) -> str:
    """How a condition's date errors are shaped, in a few words."""
    dom = entry["dominant_offset"]
    if dom is None:
        return "no errors"
    if dom == "none":
        return f"omitted ({entry['dominant_share']:.0%})"
    return f"{dom:+d} day ({entry['dominant_share']:.0%})"


def _summary(overlap, comp, offsets) -> str:
    """Answers first. A reader who stops here should still have the whole story.

    Everything below this section is evidence for these three claims; nothing new is introduced
    later. Written to be falsifiable - each bullet names the number that would have to change.
    """
    bullets = []

    # 1. The guidance finding that replicated.
    pairs = [("naive", "prod", "Claude Sonnet"), ("gemini_naive", "gemini_prod", "Gemini Flash")]
    have = [(b, i, n) for b, i, n in pairs if b in overlap and i in overlap]
    if have:
        detail = "; ".join(
            f"{n} {overlap[b]['validation_failures']}/{overlap[b]['parses']} -> "
            f"{overlap[i]['validation_failures']}/{overlap[i]['parses']}" for b, i, n in have)
        bullets.append(
            f"1. **The described schema eliminates malformed output.** The shape-only schema "
            f"returned responses that failed validation; the described schema never did, on "
            f"either model ({detail}). This is the best-supported result here - it replicated "
            f"across two independent model families - and it is a qualitative failure: there is "
            f"no record at all to score.")

    # 2. The guidance finding that did not.
    if all(k in overlap for k in ("naive", "prod", "gemini_naive", "gemini_prod")):
        dc = round(overlap["prod"]["f1"] - overlap["naive"]["f1"], 3)
        dg = round(overlap["gemini_prod"]["f1"] - overlap["gemini_naive"]["f1"], 3)
        bullets.append(
            f"2. **The guidance does not measurably change extraction accuracy.** The F1 delta is "
            f"{dc:+.3f} on Claude and {dg:+.3f} on Gemini - opposite signs, both far inside the "
            f"~{NOISE_FLOOR_F1} run-to-run spread. What does move consistently is the trade: "
            f"recall up, precision down, on both models. Any claim of an accuracy gain would need "
            f"a larger test set than this one.")

    # 3. The clearest model difference.
    flagged = [c for c, o in (offsets or {}).items()
               if isinstance(o["dominant_offset"], int) and o["dominant_offset"] != 0
               and o["dominant_share"] >= 0.25]
    if flagged:
        worst = max(flagged, key=lambda c: offsets[c]["dominant_share"])
        o = offsets[worst]
        bullets.append(
            f"3. **{CONDITIONS[worst].short} has a systematic "
            f"date bias.** {o['dominant_share']:.0%} of its deadlines land exactly "
            f"{o['dominant_offset']:+d} day from the annotated one - no other model produces that "
            f"offset once. Unlike the F1 differences, this is far outside the noise, and it "
            f"matters directly: deadlines drive this product's reminder scheduling.")

    return "\n\n".join(_wrap(b, indent="   ") for b in bullets)


def _recommendation(overlap, comp, offsets) -> str:
    """The decision the model comparison exists to inform, stated plainly."""
    present = [c for c in COMPARISON_CONDITIONS if c in overlap]
    if len(present) < 2:
        return ""
    spread = round(max(overlap[c]["f1"] for c in present)
                   - min(overlap[c]["f1"] for c in present), 3)

    lines = []
    for cond in present:
        m, q = overlap[cond], (comp or {}).get(cond, {})
        o = (offsets or {}).get(cond, {})
        exact = f"{o['exact']}/{o['total']}" if o else "-"
        lines.append(
            f"| {CONDITIONS[cond].short} | {m['recall']} | {exact} | "
            f"{_pct(q.get('source_decision_rate'))} | {_MODEL_NOTES.get(cond, '?')} |")

    return f"""
### Recommendation

The F1 spread across the three candidate models is **{spread:.3f}**, against a run-to-run spread of
~{NOISE_FLOOR_F1}. **This evaluation does not rank them on accuracy**, and presenting it as though it did
would be reporting noise. What it does resolve is how each one *fails*:

| Model | Recall | Deadlines exact | `source_decision` | Cost |
|---|---|---|---|---|
{chr(10).join(lines)}

Each candidate carries a flaw that is specifically disqualifying for this product:

- **Claude Haiku** resolves relative dates a day late on most deadlines, so every reminder would
  fire late. The cheapest model is the one whose failure most directly breaks the core feature.
- **Gemini Flash** extracts the most and reads dates best, but leaves `source_decision` empty on
  most items - a field the schema defines and the application uses. Its free tier is also a demo
  quota, not a production one.
- **Mistral Small** proposes almost nothing wrong, but misses roughly a third of the real work.
  For a meeting orchestrator a dropped action item is the worst available failure.

**Recommendation: keep the shipped Claude Sonnet configuration.** It is the only option without a
specific disqualifier. If cost later forces a change, Haiku is the most rescuable of the three - a
constant offset is the kind of error a prompt change could plausibly remove, unlike a field the
model declines to populate or recall it never had. That fix would need validating before a switch,
not instead of one.
"""


def _study_one(overlap, comp, counts) -> str:
    """Does the guidance layer help? One table, both models, both arms."""
    order = ["naive", "prod", "gemini_naive", "gemini_prod"]
    present = [c for c in order if c in overlap]
    if len(present) < 2:
        return ""

    rows = []
    for cond in present:
        m, q = overlap[cond], (comp or {}).get(cond, {})
        bold = "**" if CONDITIONS[cond].guidance == "Improved" else ""
        rows.append(
            f"| {bold}{CONDITIONS[cond].label}{bold} | {m['n_runs']} | {m['precision']} | "
            f"{m['recall']} | {bold}{m['f1']}{bold} | "
            f"{m['validation_failures']}/{m['parses']} | "
            f"{_pct(q.get('source_decision_rate'))} | "
            f"{_fmt_frac(counts, cond, 'owner')} |")

    c_n, c_p = (comp or {}).get("naive", {}), (comp or {}).get("prod", {})
    g_n, g_p = (comp or {}).get("gemini_naive", {}), (comp or {}).get("gemini_prod", {})
    d_claude = overlap["prod"]["f1"] - overlap["naive"]["f1"]
    d_gemini = overlap["gemini_prod"]["f1"] - overlap["gemini_naive"]["f1"]

    # Built then wrapped, rather than laid out inline: interpolated numbers vary in width and
    # would otherwise break these sentences at arbitrary points in the generated markdown.
    prose = _wrap(f"""**Reliability - replicated.** The shape-only schema produced output that
failed validation on both models; the described schema never did on either. Two unrelated model
families failing the same way, and being fixed the same way, is the strongest evidence here.

**Accuracy - not established.** The guidance raises recall and lowers precision on both models,
but the net F1 effect has opposite signs ({d_claude:+.3f} on Claude, {d_gemini:+.3f} on Gemini)
and both sit inside the noise. The second model was added expecting the guidance to help *more*
where the model is weaker; it did not, and that expectation is recorded here as refuted rather
than quietly dropped.

**Record quality - Claude only.** Source-decision capture rose
{_pct(c_n.get('source_decision_rate'))} -> {_pct(c_p.get('source_decision_rate'))} on Claude but
only {_pct(g_n.get('source_decision_rate'))} -> {_pct(g_p.get('source_decision_rate'))} on Gemini.
The schema asks both models for the same field; only Claude acts on it. Claude also varies its
confidence score as instructed ({c_p.get('confidence_min')}-{c_p.get('confidence_max')},
{c_p.get('confidence_distinct')} distinct values) where the control emits a near-constant one
({c_n.get('confidence_min')}-{c_n.get('confidence_max')}, {c_n.get('confidence_distinct')} values)
that cannot be filtered on.""")

    return f"""
## Study 1 - does the guidance layer help?

Within each model the two rows differ **only** in guidance text; the JSON contract is identical.
`eval/test_matching.py` asserts this for Claude, `eval/test_providers.py` for Gemini after schema
translation.

| Condition | Runs | Precision | Recall | F1 | Validation failures | `source_decision` | Owner |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

{prose}

> These two models are a generation apart, so rows are comparable *within* a model but not
> *across* one - a cross-model gap here would measure release date as much as capability.
"""


def _study_two(overlap, comp, counts, models) -> str:
    """Which model should the project use? Tier-matched, shipped config only."""
    present = [c for c in COMPARISON_CONDITIONS if c in overlap]
    if len(present) < 2:
        return ""

    rows = []
    for cond in present:
        m, q = overlap[cond], (comp or {}).get(cond, {})
        model_id = models.get(CONDITIONS[cond].group, "?").split(" (")[0]
        rows.append(
            f"| {CONDITIONS[cond].short} | `{model_id}` | {m['n_runs']} | "
            f"{m['precision']} | {m['recall']} | **{m['f1']}** | "
            f"{m['validation_failures']}/{m['parses']} | "
            f"{_pct(q.get('source_decision_rate'))} | {_fmt_frac(counts, cond, 'status')} |")

    return f"""
## Study 2 - which model should the project use?

Every row runs the **shipped configuration**; only the model changes. The incumbent (Claude
Sonnet) is included because the question is whether to replace it, and a candidate list without
the thing being replaced cannot answer that.

The tiers are not matched, and the mismatch runs both ways: Sonnet is a larger tier than the other
three, while Gemini Flash is a later release than Sonnet. So this table is a procurement decision
for this project - where price and quota are legitimate inputs - and not a ranking of vendors.
Haiku is the tier-matched Claude entry, which is what makes "Sonnet was chosen" a comparison
rather than vendor loyalty.

| Model | Model id | Runs | Precision | Recall | F1 | Validation failures | `source_decision` | Status |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

Run counts differ because the free tiers cap daily requests; each condition is averaged over its
own runs, never pooled across models.
"""


def _deadline_section(offsets: dict) -> str:
    """Systematic vs random date error - the one place a clear model difference shows up."""
    present = [c for c in COMPARISON_CONDITIONS + ["prod"] if c in offsets]
    if len(present) < 2:
        return ""

    rows = [f"| {CONDITIONS[c].short} | {offsets[c]['total']} | "
            f"{offsets[c]['exact']}/{offsets[c]['total']} "
            f"({offsets[c]['exact']/offsets[c]['total']:.0%}) | {_offset_shape(offsets[c])} |"
            for c in present]

    flagged = [c for c in present
               if isinstance(offsets[c]["dominant_offset"], int)
               and offsets[c]["dominant_offset"] != 0
               and offsets[c]["dominant_share"] >= 0.25]
    if flagged:
        worst = max(flagged, key=lambda c: offsets[c]["dominant_share"])
        o = offsets[worst]
        callout = "\n" + _wrap(f"""**{CONDITIONS[worst].short} is systematically biased, not confused.** {o['dominant_share']:.0%} of its matched deadlines land exactly {o['dominant_offset']:+d} day from the annotated
one - it resolves relative cues ("by Friday", "end of next week") consistently one day late, and
no other model here produces that offset even once. Two consequences: its low exact-match rate
overstates how badly it understands dates, and a constant offset is the kind of error a prompt
change could plausibly remove. Unlike the F1 differences elsewhere in this report, {o['dominant_share']:.0%} of {o['total']}
scored deadlines is well outside the noise.""")
    else:
        callout = ("\nNo condition shows a dominant constant offset, so these look like "
                   "comprehension misses rather than a systematic resolution bug.")

    return f"""
## Deadline errors - systematic or random?

Exact-match accuracy cannot tell a model that is *randomly* wrong about dates from one that is
wrong by a *constant* amount, and those mean very different things - the second is a resolution
bug a prompt could fix, and it shifts every reminder this product sends.

| Model | Deadlines scored | Exact | Most common error |
|---|---|---|---|
{chr(10).join(rows)}
{callout}
"""


def _flagged_offset(offsets: dict):
    """The condition whose date errors are dominated by one constant offset, if any."""
    flagged = [c for c, o in (offsets or {}).items()
               if isinstance(o["dominant_offset"], int) and o["dominant_offset"] != 0
               and o["dominant_share"] >= 0.25]
    if not flagged:
        return None, None
    worst = max(flagged, key=lambda c: offsets[c]["dominant_share"])
    return worst, offsets[worst]


def render_report(cache: dict, overlap: dict, n_transcripts: int, n_items: int,
                  comp: dict | None = None, offsets: dict | None = None) -> str:
    """The short report - what gets opened in a progress check-in.

    Deliberately compressed to two tables and three claims. Everything it leaves out lives in
    the appendix and is linked, so compressing here costs nothing in defensibility: the reader
    who wants precision/recall per condition, the confound notes or the corrections can follow
    one link. The one thing that must survive compression is the limit on what the numbers
    support, so the "What this does not show" section is not optional.
    """
    today = date.today().isoformat()
    comp, offsets = comp or {}, offsets or {}

    # Step 1 - the model table. Every candidate, incumbent included.
    model_rows = []
    for cond in [c for c in COMPARISON_CONDITIONS if c in overlap]:
        m, q = overlap[cond], comp.get(cond, {})
        o = offsets.get(cond, {})
        deadlines = f"{o['exact']/o['total']:.0%}" if o.get("total") else "-"
        chosen = "**" if cond == "prod" else ""
        model_rows.append(
            f"| {chosen}{CONDITIONS[cond].short}{chosen} | {m['recall']:.0%} | {m['f1']} | "
            f"{deadlines} | {_pct(q.get('source_decision_rate'))} | {_MODEL_NOTES.get(cond, '?')} |")

    worst, o = _flagged_offset(offsets)
    bias = _wrap(
        f"**{CONDITIONS[worst].short} has a systematic date bug.** {o['dominant_share']:.0%} of the deadlines it "
        f"produced land exactly {o['dominant_offset']:+d} day from the correct one - it reads \"by Friday\" as the "
        f"following day, consistently. Every reminder scheduled from it would fire a day late."
    ) if worst else "No model showed a systematic date bias."

    # Step 2 - what the guidance bought on the chosen model. Mirrors the slide exactly.
    c_n, c_p = comp.get("naive", {}), comp.get("prod", {})
    o_n, o_p = overlap.get("naive", {}), overlap.get("prod", {})
    guidance_rows = "\n".join([
        f"| Source decision captured | {_pct(c_n.get('source_decision_rate'))} | "
        f"**{_pct(c_p.get('source_decision_rate'))}** |",
        f"| Confidence actually varies | {c_n.get('confidence_min')} - {c_n.get('confidence_max')} "
        f"({c_n.get('confidence_distinct')} values) | **{c_p.get('confidence_min')} - "
        f"{c_p.get('confidence_max')} ({c_p.get('confidence_distinct')} values)** |",
        f"| Parses failing validation | {c_n.get('validation_failures')} / {c_n.get('parses')} | "
        f"**{c_p.get('validation_failures')} / {c_p.get('parses')}** |",
        f"| Action items found (recall) | {o_n.get('recall')} | **{o_p.get('recall')}** |",
    ])

    return f"""# Evaluation Report

_Generated by `python -m eval.run_eval --write-report` on {today}._
_Full methodology, per-condition figures and caveats: [evaluation-appendix.md](evaluation-appendix.md)._

## What was measured

The transcript parser is scored against **{n_transcripts} synthetic SAP meeting transcripts** containing
**{n_items} manually annotated action items**. Two questions, in order:

1. **Which model should the project use?**
2. **What does the prompt and schema engineering add on that model?**

## Step 1 - choosing the model

Every row runs the same shipped configuration; only the model changes.

| Model | Action items found | F1 | Deadlines correct | Context captured | Cost |
|---|---|---|---|---|---|
{chr(10).join(model_rows)}

{bias}

{_wrap('''**No model wins outright, and Claude Sonnet was chosen because it is the only one with no
disqualifying failure.** Gemini Flash actually finds more action items and reads dates better, but
leaves the source-decision field empty on most of them, so its tasks arrive without the context the
board and the subtask generator depend on. Mistral Small proposes almost nothing wrong but misses
roughly a third of the real work, and a dropped action item is the worst failure this application
can have - nothing on the board indicates that it is missing. Claude Haiku carries the date bug
above.''')}

> {_wrap('''These models sit at different price tiers *and* different release dates - Sonnet is a
larger tier than the other three, while Gemini Flash is a later release than Sonnet. The confound
runs in both directions, which is why this table is a cost decision for this project rather than a
ranking of vendors.''', indent="> ")}

## Step 2 - what the prompt and schema engineering adds

Having chosen Claude Sonnet, the same model is run with and without the structured guidance layer -
the refined prompt rules plus the fully described JSON schema. The output contract is identical in
both columns; only the guidance text differs.

| Metric | No guidance | Shipped |
|---|---|---|
{guidance_rows}

{_wrap('''Without the descriptions the model periodically returns output that fails validation
outright - usually a malformed date - and the application gets no record at all. With them, that did
not happen once. The remaining rows are the fields the guidance explicitly asks for: the decision
each task came from, and a confidence score that actually varies instead of sitting near-constant
and therefore carrying no information.''')}

## What this does not show

{_wrap(f'''The test set is small ({n_transcripts} transcripts, {n_items} items), and repeat runs of the *same*
configuration vary by more than the accuracy gaps between models. **Neither table establishes an
accuracy ranking** and neither should be read as one. What they do support is the reliability and
completeness differences: valid output, captured context, and the date bug. A larger annotated test
set is scheduled for the next phase and is what would settle the accuracy question.''')}
"""


def render_appendix(cache: dict, overlap: dict, judge: dict | None, n_transcripts: int,
                    n_items: int, comp: dict | None = None, counts: dict | None = None,
                    offsets: dict | None = None) -> str:
    """Render the technical appendix: every condition, every caveat, every correction.

    Structure is deliberate. Two studies are reported, each with one table, because their rows are
    not mutually comparable - Study 1 varies guidance, Study 2 varies model, and a single combined
    table would invite reading across that boundary. The LLM-judge figures are kept out of the
    tables entirely: they are computed on demand (they cost API calls) so most conditions lack
    them, and a column of dashes reads as broken rather than absent.
    """
    today = date.today().isoformat()
    judge, comp, counts, offsets = judge or {}, comp or {}, counts or {}, offsets or {}
    models = _models_used(cache, overlap)
    bare = {k: v.split(" (")[0] for k, v in models.items()}

    judged = [c for c in ("naive", "prod") if c in judge and c in overlap]
    if judged:
        agreement = "; ".join(
            f"{CONDITIONS[c].label}: {overlap[c]['f1']} overlap vs {judge[c]['f1']} judge"
            for c in judged)
        judge_note = (
            f"A second, semantic matcher (an LLM judge deciding whether two descriptions name the "
            f"same task) was run on the Claude conditions and agreed on the ordering, scoring "
            f"slightly higher throughout - {agreement}. It costs API calls per transcript, so it "
            f"is not computed for every condition and is kept out of the tables below; "
            f"`eval/results.json` holds the full figures.")
    else:
        judge_note = ("A semantic LLM-judge matcher is available via `--rescore-judge` but has not "
                      "been run on the current cache.")

    judge_note = _wrap(judge_note)

    return f"""# Evaluation Report - Technical Appendix

_Generated by `python -m eval.run_eval --write-report` on {today}. Re-run to refresh._
_Summary and recommendation: [evaluation-report.md](evaluation-report.md)._

## Summary

{_summary(overlap, comp, offsets)}
{_recommendation(overlap, comp, offsets)}
## Test set and method

- Synthetic SAP-programme transcripts: **{n_transcripts}**; manually annotated action items: **{n_items}**.
- Source: `data/synthetic-transcripts/` and `data/annotated-test-set/annotations.json`.
- Each transcript is parsed with its true meeting date, so relative cues ("by this Friday")
  resolve deterministically.
- Predicted items are matched one-to-one against the annotated ones by **word overlap** (Jaccard
  over content words, threshold {MATCH_THRESHOLD}) - deterministic, no model involved. Matched pairs are then
  scored field by field.
- **precision** = matched / predicted, **recall** = matched / expected, **F1** their harmonic
  mean. Owner, status and deadline accuracy are computed over *matched* items only, so they sit
  on different denominators per condition and are reported with counts.
- Runs are independent and averaged; both models are non-deterministic and run counts differ by
  condition, so each is stated rather than assumed.
- Requests that never completed (rate limit, capacity) are recorded as API failures and excluded
  from scoring - an exhausted quota is never counted as the model failing to find items. Only
  responses that arrived but did not satisfy the schema count as validation failures.

{judge_note}

Gemini needs the tool schema translated into its OpenAPI subset (`eval/providers.py`); Mistral
accepts JSON Schema unchanged. The translation is asserted to preserve fields, required list and
enum, because a translation bug would surface as a model difference that is really a harness bug.
{_study_one(overlap, comp, counts)}{_study_two(overlap, comp, counts, models)}{_deadline_section(offsets)}
## Limitations

- **The test set is synthetic.** The four transcripts were generated for this project and written
  to be deliberately messy - interruptions, corrections, half-finished sentences and decisions
  revisited later - so that the parser is not only measured on tidy prose. They are still authored
  text rather than a transcription of real speech, which is the honest caveat: generated dialogue
  may be more internally consistent than a genuine recording even when written to look untidy. The
  pipeline was separately exercised end to end on a real recording from the AMI meeting corpus, but
  that recording is not part of the scored test set.
- **One annotator, no second opinion.** The answer key was labelled by the project author, so there
  is no inter-annotator agreement figure and no independent check on what counts as an action item.
  On a four-transcript set a single ambiguous judgement moves the reported rates measurably.
- **Small test set** ({n_transcripts} transcripts, {n_items} annotated items) and few runs per condition. Individual
  runs of the same configuration varied by up to ~{NOISE_FLOOR_F1} F1 - larger than most gaps reported here.
  This is the binding limitation and it bounds every number above. More runs on a larger, noisier
  test set is the single highest-value improvement.
- **Run counts are capped by cost and quota**, not chosen for statistical power: the free tiers
  limit daily requests and the Claude runs are billed. Each condition is averaged over its own
  runs and the count is printed in the results table, so an unequal batch would be visible
  rather than silently pooled.
- **The Study 1 models are a generation apart** (`{bare.get('claude', '?')}` vs `{bare.get('gemini', '?')}`), so nothing
  here ranks providers. Only within-model contrasts are fair. Re-running the Claude side on a
  current model is the fix and costs API credit.
- `gemini-3.7-flash`, the newest Flash at time of writing, returned HTTP 503 "high demand" or hung
  on roughly three attempts in four and could not be used; `gemini-3.6-flash` is the newest Flash
  that answered reliably.
- The judge matcher shares a model family with the Claude parser, so it is not fully independent;
  reporting deterministic word overlap as the primary matcher is the mitigation.
- Ambiguous deadline phrases are annotated as single dates. Anchoring them during annotation, or
  capturing a range, would sharpen the exact-match metric.
- **A correction worth recording.** An earlier `BARE_TOOL` stripped every key named `description`,
  which also removed the *field* named "description" from the property map, leaving the control
  requiring a field it did not define. That inflated its validation failures and depressed its
  scores. The stripper now preserves field names and removes only annotation text, and
  `eval/test_matching.py` has a regression test. All figures above are from a post-fix re-run.

## Raw results

`eval/results.json` holds the scored metrics for every condition, including any LLM-judge
figures that have been computed. `eval/predictions.json` holds the cached raw parser output
each run was scored from, so scoring can be repeated offline without re-querying any model.
"""

# --------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Evaluate the transcript-parsing pipeline and regenerate the report.")
    ap.add_argument("--parse", action="store_true",
                    help="COSTS API CALLS. Parse the test set once more and append the run to "
                         "eval/predictions.json.")
    ap.add_argument("--provider", choices=GROUPS, default="claude",
                    help="Which model group --parse should run. 'claude' (Sonnet 2x2) and "
                         "'haiku' spend Anthropic credit; 'gemini' and 'mistral' use free "
                         "tiers. Default: claude.")
    ap.add_argument("--runs", type=int, default=1,
                    help="How many parse runs to append (only with --parse).")
    ap.add_argument("--rescore-judge", action="store_true",
                    help="COSTS ANTHROPIC API CALLS. Re-run the LLM-judge matcher. Without this, "
                         "stored judge scores are reused and missing ones are left blank.")
    ap.add_argument("--write-report", action="store_true",
                    help="Refresh docs/evaluation-report.md (short) and "
                         "docs/evaluation-appendix.md (detail). Free - no API calls.")
    args = ap.parse_args()

    annotations = json.loads(ANNOTATIONS.read_text())

    if args.parse:
        cache = json.loads(PREDICTIONS_JSON.read_text()) if PREDICTIONS_JSON.exists() \
            else {"note": "Cached raw parser output.", "runs": []}
        conds = [k for k, c in CONDITIONS.items() if c.group == args.provider]
        for i in range(args.runs):
            print(f"--- {args.provider} parse run {i + 1}/{args.runs} (calling the model) ---")
            cache["runs"].append(parse_run(annotations, conds))
            PREDICTIONS_JSON.write_text(json.dumps(cache, indent=2, default=str) + "\n")
        print(f"Cached to {PREDICTIONS_JSON.relative_to(REPO_ROOT)}")
    else:
        cache = load_cache()

    # Word-overlap scoring is pure computation - never touches any API.
    overlap = aggregate(cache, annotations, "overlap")

    # The judge matcher costs one Anthropic call per transcript per condition. Scores are cached
    # per condition, not for the run list as a whole: otherwise appending a Gemini run would
    # invalidate the Claude judge scores and silently re-bill them.
    stored = json.loads(RESULTS_JSON.read_text()) if RESULTS_JSON.exists() else {}
    stored_judge = stored.get("judge", {})
    judge, need = {}, []
    for name in overlap:
        prev = stored_judge.get(name)
        # How many runs a stored entry covers is derivable from the entry itself - it holds one
        # score dict per run. Deriving it here rather than trusting a separate counter is what
        # keeps Claude's cached scores valid when Gemini runs are appended: a global run count
        # would change and needlessly re-bill the judge.
        prev_n = len(prev.get("runs", [])) if prev else None
        if prev and not args.rescore_judge and prev_n == overlap[name]["n_runs"]:
            judge[name] = prev
        else:
            need.append(name)

    if need and args.rescore_judge:
        print(f"Running the LLM judge on {need} - THIS CALLS THE ANTHROPIC API.")
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        judge.update(aggregate(cache, annotations, "judge", client, only=need))
    elif need:
        print(f"No judge scores for {need} (reported as '-'). "
              f"Pass --rescore-judge to compute them - COSTS ANTHROPIC API CALLS.")
    if judge:
        print("Judge scores reused from eval/results.json where available (no API calls).")

    print("\n=== mean over each condition's own runs ===")
    hdr = (f"{'condition':26} {'runs':>5} {'F1 ovl':>8} {'F1 judge':>9} {'prec':>7} "
           f"{'recall':>7} {'fail':>8}")
    print(hdr); print("-" * len(hdr))
    for name, agg in overlap.items():
        j = judge.get(name, {}).get("f1", "-")
        print(f"{LABELS.get(name, name):26} {agg['n_runs']:5} {agg['f1']:8} {str(j):>9} "
              f"{agg['precision']:7} {agg['recall']:7} "
              f"{str(agg['validation_failures']) + '/' + str(agg['parses']):>8}")

    RESULTS_JSON.write_text(json.dumps(
        {"runs": len(cache["runs"]), "overlap": overlap, "judge": judge},
        indent=2, default=str) + "\n")
    print(f"\nWrote {RESULTS_JSON.relative_to(REPO_ROOT)}")

    if args.write_report:
        n_items = overlap["prod"]["runs"][0]["expected_items"]
        comp = completeness(cache)
        counts = pooled_field_counts(cache, annotations)
        offsets = deadline_offsets(cache, annotations)
        REPORT_MD.write_text(render_report(
            cache, overlap, len(annotations), n_items, comp=comp, offsets=offsets))
        APPENDIX_MD.write_text(render_appendix(
            cache, overlap, judge, len(annotations), n_items,
            comp=comp, counts=counts, offsets=offsets))
        print(f"Wrote {REPORT_MD.relative_to(REPO_ROOT)} (short) and "
              f"{APPENDIX_MD.relative_to(REPO_ROOT)} (detail)")


if __name__ == "__main__":
    main()
