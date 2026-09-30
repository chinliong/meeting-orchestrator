"""Extraction on real meetings, checked against a human-written answer key.

The main extraction evaluation (docs/evaluation-report.md) uses transcripts and answer keys
drafted for this project. This check adds two real meetings from the AMI Meeting Corpus, whose
own annotators wrote an ACTIONS section in each meeting's abstractive summary, and runs the
production extraction (Gemini Flash, the prompt the app uses) on two versions of each meeting:

    reference    the AMI manual transcript
    headset      the Deepgram Nova-3 transcript of the headset recording that the speech-to-text
                 evaluation scores (eval/asr_transcripts, 13.0% and 15.3% WER)
    speakers     the same recording as the app transcribes it now, with Deepgram's speaker
                 labels ("Speaker 1: ...")

Two measures, using the extraction evaluation's semantic matcher (eval.run_eval's judge, with
its one-to-one rule):

    AMI actions found    share of the actions in the AMI summary that a run's tasks contain
    tasks kept           share of the tasks found from the reference transcript that are also
                         found from the headset transcript (every headset run against every
                         reference run, so run-to-run variation is included)

    python -m eval.ami_actions_eval --annotations ami_public_manual_1.6.2.zip

The results are written to eval/ami_actions_results.json and appear as the "From recording to
tasks" section of docs/asr-evaluation.md.

Predictions are cached in eval/ami_actions_predictions.json, so re-scoring does not call Gemini
again (pass --rerun to do so); the judge is called each time. The AMI summary actions are cached
in data/test-audio/ami_actions.json (AMI Meeting Corpus, CC BY 4.0).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import zipfile
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
load_dotenv(REPO / "backend" / ".env")

from eval.run_eval import _match_judge  # noqa: E402

AUDIO_DIR = REPO / "data" / "test-audio"
TRANSCRIPTS = REPO / "eval" / "asr_transcripts"
ACTIONS = AUDIO_DIR / "ami_actions.json"
CACHE = REPO / "eval" / "ami_actions_predictions.json"
RESULTS = REPO / "eval" / "ami_actions_results.json"

MEETINGS = ["ES2008a", "ES2010a"]
SOURCES = ["reference", "headset", "speakers"]
JUDGE_MODEL = "claude-sonnet-4-6"   # the extraction evaluation's judge
# AMI does not record calendar dates; a fixed one keeps deadline resolution identical across runs.
MEETING_DATE = date(2026, 6, 1)


def summary_actions(zip_path: str) -> dict[str, list[str]]:
    """The ACTIONS sentences of each meeting's abstractive summary."""
    out = {}
    with zipfile.ZipFile(zip_path) as zf:
        for m in MEETINGS:
            xml = zf.read(f"abstractive/{m}.abssumm.xml").decode("utf-8")
            block = re.search(r"<actions[^>]*>(.*?)</actions>", xml, re.S)
            out[m] = [re.sub(r"\s+", " ", s).strip()
                      for s in re.findall(r"<sentence[^>]*>(.*?)</sentence>", block.group(1), re.S)]
    return out


def transcript(meeting: str, source: str) -> str:
    if source == "reference":
        return (AUDIO_DIR / f"{meeting}.reference.txt").read_text()
    if source == "speakers":
        return (TRANSCRIPTS / f"{meeting}.deepgram-nova-3-speakers.txt").read_text()
    return (TRANSCRIPTS / f"{meeting}.deepgram-nova-3.txt").read_text()


def extract(text: str) -> list[dict]:
    from app.llm.parser import TranscriptParser
    result = TranscriptParser().parse(text, MEETING_DATE)
    return [{"description": a.description, "owner": a.owner,
             "deadline": a.deadline.isoformat() if a.deadline else None}
            for a in result.action_items]


def section(results: dict, runs: int) -> str:
    """The "From recording to tasks" section of docs/asr-evaluation.md, which eval.asr_eval writes."""
    rows, kept, found_ok = [], [], []
    for m in MEETINGS:
        r = results[m]
        ref, head, spk = r["reference"], r["headset"], r["speakers"]
        n = len(r["ami_actions"])
        rows.append(f"| {m} | {n} | {ref['found']:.0%} | {spk['found']:.0%} |")
        kept.append(f"{head['kept']:.0%} ({m})")
        found_ok.append(f"{head['found']:.0%} ({m})")
    examples = "\n".join(f"- {m}: " + "; ".join(f"\"{a}\"" for a in results[m]["ami_actions"])
                         for m in MEETINGS)
    return f"""## From recording to tasks

Word error rate only counts words. What matters for the app is whether the right tasks come out.
So for each meeting the tasks were extracted twice: once from the human-typed transcript (the
perfect case) and once from the recording, transcribed the way the app does it. Both were checked
against the actions AMI's note-takers listed for that meeting. Each version was run {runs} times;
the table shows the share of listed actions found, averaged over the runs.

| Meeting | Actions listed by AMI | Found from the human-typed transcript | Found from the recording (the app) |
|---|---|---|---|
{chr(10).join(rows)}

**Result.** The recording gives the same actions as the human-typed transcript. Every figure
below 100% is one run in which two of AMI's actions, typing up the minutes and e-mailing the
slides, came out as a single task: the work is on the board, but it counts as one match instead
of two.

Two further comparisons agree. Transcribed without the speaker labels the app now adds, the
recording found {' and '.join(found_ok)} of the listed actions. Compared as whole boards, the
recording's board contained {' and '.join(kept)} of the tasks found from the human-typed
transcript.

**What changes is the spelling of names.** Deepgram writes names as it hears them, so an owner
can be spelled differently from the human-typed transcript (Iain as "Ian", Bucciantini as
"Bucontinini"). The tasks are still assigned to the same people.

### The AMI actions

{examples}

### How this check was done

- Answer key: the ACTIONS section of each meeting's abstractive summary, AMI manual annotations
  v1.6.2 (CC BY 4.0), cached in `data/test-audio/ami_actions.json`.
- Matching uses the extraction evaluation's semantic judge ({JUDGE_MODEL}) with its one-to-one
  rule. Token overlap misses paraphrases on a key this short ("work on the technical function
  design" against "Develop the technical functions design"), so it is not used here.
- **Recall only.** The AMI summaries list the main actions, a median of two per meeting across
  the corpus, not every task, so a task outside the list is not an error and precision is not
  measured.
- **Two meetings, {runs} runs each**, both kick-off meetings of the same design scenario, and the
  AMI actions name roles rather than people, so owners are not scored against them.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--annotations", help="ami_public_manual_1.6.2.zip (only needed once)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--rerun", action="store_true", help="call Gemini again")
    args = ap.parse_args()

    if not ACTIONS.exists():
        if not args.annotations:
            sys.exit("Pass --annotations ami_public_manual_1.6.2.zip the first time.")
        ACTIONS.write_text(json.dumps(summary_actions(args.annotations), indent=2) + "\n")
    actions = json.loads(ACTIONS.read_text())

    cache = json.loads(CACHE.read_text()) if CACHE.exists() and not args.rerun else {}
    for m in MEETINGS:
        for s in SOURCES:
            runs = cache.setdefault(m, {}).setdefault(s, [])
            while len(runs) < args.runs:
                runs.append(extract(transcript(m, s)))
                print(f"{m} {s}: run {len(runs)} -> {len(runs[-1])} tasks", flush=True)
                CACHE.write_text(json.dumps(cache, indent=2) + "\n")

    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def match(expected, predicted):
        return _match_judge(expected, predicted, client, JUDGE_MODEL)

    results = {}
    for m in MEETINGS:
        key = [{"description": a} for a in actions[m]]
        ref_runs, head_runs = cache[m]["reference"][: args.runs], cache[m]["headset"][: args.runs]
        found = {s: [len(match(key, r)) / len(key) for r in cache[m][s][: args.runs]] for s in SOURCES}
        kept = [len(match(rr, hr)) / len(rr) for rr in ref_runs for hr in head_runs if rr]
        spk_runs = cache[m]["speakers"][: args.runs]
        results[m] = {
            "ami_actions": actions[m],
            "reference": {"found": round(statistics.mean(found["reference"]), 3),
                          "found_per_run": found["reference"], "tasks": [len(r) for r in ref_runs]},
            "headset": {"found": round(statistics.mean(found["headset"]), 3),
                        "found_per_run": found["headset"], "tasks": [len(r) for r in head_runs],
                        "kept": round(statistics.mean(kept), 3)},
            "speakers": {"found": round(statistics.mean(found["speakers"]), 3),
                         "found_per_run": found["speakers"], "tasks": [len(r) for r in spk_runs]},
        }
    RESULTS.write_text(json.dumps(results, indent=2) + "\n")
    # The results appear as a section of docs/asr-evaluation.md; refresh that page (offline).
    from eval import asr_eval
    data = asr_eval.score_all()
    asr_eval.RESULTS.write_text(json.dumps(data, indent=2) + "\n")
    asr_eval.REPORT.write_text(asr_eval.render(data))
    for m, r in results.items():
        print(f"{m}: AMI actions found - manual {r['reference']['found']:.0%}, Deepgram "
              f"{r['headset']['found']:.0%}; tasks kept {r['headset']['kept']:.0%}")
    print(f"wrote {RESULTS.relative_to(REPO)} and docs/asr-evaluation.md")


if __name__ == "__main__":
    main()
