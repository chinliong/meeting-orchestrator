"""Speech-to-text evaluation (Objective 4).

Scores each Whisper configuration against the AMI manual reference transcript for ES2008a,
using word error rate over Whisper's own EnglishTextNormalizer - the same normaliser the
Whisper paper uses, which reconciles British and American spellings so a model is not penalised
for writing "color" where AMI wrote "colour".

Transcripts are cached in eval/asr_transcripts/ so scoring re-runs without re-running any model,
matching how the transcript-parsing harness caches predictions.

    python -m eval.asr_eval      # score the cached transcripts, rewrite the report
"""
from __future__ import annotations

import argparse
import json
import random
import textwrap
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from whisper.normalizers import EnglishTextNormalizer

REPO = Path(__file__).resolve().parent.parent
TRANSCRIPTS = REPO / "eval" / "asr_transcripts"
REF_DIR = REPO / "data" / "test-audio"
RESULTS = REPO / "eval" / "asr_results.json"
REPORT = REPO / "docs" / "asr-evaluation.md"
BOOTSTRAP_BLOCK = 50            # reference words per resampled block
BOOTSTRAP_N = 2000              # resamples; seeded, so the intervals are reproducible


@dataclass(frozen=True)
class Backend:
    label: str
    where: str                  # "hosted" or "local" - the deployment, not the model
    note: str = ""


# Ordered best-first within each deployment. Timings come from the .timing.json sidecars.
BACKENDS = {
    "deepgram-nova-3":        Backend("Deepgram Nova-3", "hosted"),
    "groq-large-v3":          Backend("Whisper large-v3", "hosted"),
    "groq-turbo":             Backend("Whisper large-v3-turbo", "hosted"),
    "local-turbo":            Backend("Whisper turbo", "local"),
    "local-medium":           Backend("Whisper medium", "local"),
    "local-small":            Backend("Whisper small", "local"),
    "local-base":             Backend("Whisper base", "local",
                                      note="the library default before this evaluation"),
    "local-large-v3":         Backend("Whisper large-v3", "local",
                                      note="hallucination loops - see below"),
    "local-turbo-perchannel": Backend("Whisper turbo, per-channel", "local",
                                      note="four headset channels merged; microphone bleed "
                                           "duplicates most speech"),
}

# The two AMI meetings, with the share of reference words spoken over another speaker.
MEETINGS = {
    "ES2008a": {"seconds": 1043.0, "overlap": "9.4%", "minutes": 17.4},
    "ES2010a": {"seconds": 644.3, "overlap": "19.3%", "minutes": 10.7},
}

# The models compared in the body; the rest are the size ladder, reported in the appendix.
HEADLINE = ["deepgram-nova-3", "groq-turbo", "groq-large-v3", "local-turbo"]

def wer(ref: list[str], hyp: list[str]) -> dict:
    """Levenshtein over word sequences, with the substitution/deletion/insertion split.

    The split is what makes the result diagnostic rather than a single opaque number: a model
    that mishears is failing differently from one that never hears the words at all.
    """
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    i, j, sub, dele, ins = n, m, 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            sub += ref[i - 1] != hyp[j - 1]; i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            dele += 1; i -= 1
        else:
            ins += 1; j -= 1
    return {"wer": round((sub + dele + ins) / n, 4), "sub": sub, "del": dele, "ins": ins,
            "ref_words": n, "hyp_words": m}


def per_ref_errors(ref: list[str], hyp: list[str]) -> list[int]:
    """Levenshtein, attributing every error to the reference position where it happens.

    Needed for the bootstrap: a single WER number cannot say whether two systems differ by
    more than sampling noise, but a per-position error vector can be resampled.
    """
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    err = [0] * n
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            err[i - 1] += ref[i - 1] != hyp[j - 1]; i -= 1; j -= 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            err[i - 1] += 1; i -= 1                      # deletion
        else:
            err[max(i - 1, 0)] += 1; j -= 1              # insertion
    return err


def _blocks(err: list[int]) -> list[tuple[int, int]]:
    """(reference words, errors) for each contiguous block, the unit the bootstrap resamples."""
    return [(len(err[k:k + BOOTSTRAP_BLOCK]), sum(err[k:k + BOOTSTRAP_BLOCK]))
            for k in range(0, len(err), BOOTSTRAP_BLOCK)]


def bootstrap(err_by_key: dict[str, list[int]]) -> dict:
    """95% intervals per system, and paired intervals for the differences between them.

    Blocks are resampled once per iteration and shared across systems, so the paired interval
    measures the difference on the same audio rather than two independent noisy estimates.
    """
    blocks = {k: _blocks(e) for k, e in err_by_key.items()}
    nb = len(next(iter(blocks.values())))
    rng = random.Random(0)
    draws = [[rng.randrange(nb) for _ in range(nb)] for _ in range(BOOTSTRAP_N)]

    curves = {}
    for k, bl in blocks.items():
        curves[k] = [sum(bl[i][1] for i in d) / sum(bl[i][0] for i in d) for d in draws]

    def pct(v, q):
        return sorted(v)[int(q * len(v))]

    out = {"ci": {k: [round(pct(v, .025), 4), round(pct(v, .975), 4)] for k, v in curves.items()},
           "pairs": {}}
    keys = list(blocks)
    for a in keys:
        for c in keys:
            if a >= c:
                continue
            diffs = sorted(x - y for x, y in zip(curves[a], curves[c]))
            lo, hi = pct(diffs, .025), pct(diffs, .975)
            out["pairs"][f"{a} vs {c}"] = {
                "lo": round(lo, 4), "hi": round(hi, 4),
                "significant": bool(hi < 0 or lo > 0)}
    return out


def score_meeting(meeting: str) -> tuple[dict, dict]:
    """WER, timing and bootstrap intervals for every configuration run on one meeting."""
    norm = EnglishTextNormalizer()
    ref = norm((REF_DIR / f"{meeting}.reference.words.txt").read_text()).split()
    out, errors = {}, {}
    for key, b in BACKENDS.items():
        f = TRANSCRIPTS / f"{meeting}.{key}.txt"
        timing = TRANSCRIPTS / f"{meeting}.{key}.timing.json"
        if not f.exists() or not timing.exists():
            continue
        hyp = norm(f.read_text()).split()
        seconds = json.loads(timing.read_text())["seconds"]
        r = wer(ref, hyp)
        r.update(label=b.label, where=b.where, note=b.note, seconds=seconds,
                 realtime_factor=round(MEETINGS[meeting]["seconds"] / seconds, 1))
        out[key] = r
        errors[key] = per_ref_errors(ref, hyp)
    stats = bootstrap(errors)
    for key, r in out.items():
        r["ci"] = stats["ci"][key]
    return out, stats["pairs"]


def score_all() -> dict:
    """Every meeting, keyed by meeting id."""
    return {m: dict(zip(("scores", "pairs"), score_meeting(m))) for m in MEETINGS}



    argparse.ArgumentParser(description="Score the speech-to-text configurations.").parse_args()
    scores, pairs = score_all()
    RESULTS.write_text(json.dumps({"scores": scores, "pairs": pairs}, indent=2) + "\n")
    REPORT.write_text(render(scores, pairs))
    print(f"{len(scores)} configurations scored")
    print(f"wrote {RESULTS.relative_to(REPO)} and {REPORT.relative_to(REPO)}")


def _wrap(text: str, width: int = 96) -> str:
    return "\n\n".join(textwrap.fill(" ".join(p.split()), width)
                       for p in text.strip().split("\n\n"))


def _pct(v):
    return f"{v:.1%}" if v is not None else "-"


def render(data: dict) -> str:
    a, b = data["ES2008a"], data["ES2010a"]

    def row(key):
        ra, rb = a["scores"].get(key), b["scores"].get(key)
        r = ra or rb
        return (f"| {r['label']} | {r['where']} | {_pct(ra and ra['wer'])} | "
                f"{_pct(rb and rb['wer'])} | {ra['seconds']:.0f}s |")

    body = "\n".join(row(k) for k in HEADLINE if k in a["scores"] or k in b["scores"])
    ladder = "\n".join(
        f"| {a['scores'][k]['label']} | {a['scores'][k]['wer']:.1%} | "
        f"{a['scores'][k]['seconds']:.0f}s | {a['scores'][k]['note'] or ''} |"
        for k in BACKENDS if k.startswith("local-") and k in a["scores"])

    def detail(d):
        return "\n".join(
            f"| {r['label']} ({r['where']}) | {r['wer']:.1%} | "
            f"[{r['ci'][0]:.1%}, {r['ci'][1]:.1%}] | {r['sub']} | {r['del']} | {r['ins']} |"
            for r in sorted(d["scores"].values(), key=lambda v: v["wer"]))

    def sig(d, pairs):
        return "\n".join(
            f"| {k} | {v['lo']:+.1%} to {v['hi']:+.1%} | "
            f"{'**yes**' if v['significant'] else 'no'} |"
            for k, v in d["pairs"].items() if k in pairs)

    keypairs = ["deepgram-nova-3 vs groq-turbo", "groq-turbo vs local-turbo",
                "groq-large-v3 vs groq-turbo"]

    return f"""# Speech-to-Text Evaluation

_Generated by `python -m eval.asr_eval` on {date.today().isoformat()}. Re-run to refresh._

## Decision

{_wrap('''Uploads are transcribed by **Deepgram Nova-3**, with **hosted Whisper** (Groq) as an
automatic fallback. Deepgram is the more accurate of the two on both test meetings. Whisper
stays configured because Deepgram's free tier is a one-off credit while Groq's resets daily, so
the fallback is what keeps the feature alive once that credit is spent. Neither loads a model on
the server, which is what makes the audio path fit a 512 MB instance.''')}

## Results

Scored against the AMI manual transcripts. The two meetings differ in how much speech overlaps,
which is the main thing that makes meeting audio hard.

| Model | Runs on | ES2008a (9.4% overlap) | ES2010a (19.3% overlap) | Time (17 min audio) |
|---|---|---|---|---|
{body}

{_wrap('''Deepgram is ahead on both meetings and the paired bootstrap separates it from hosted
Whisper both times. The three Whisper rows are not separable from each other: the ordering of
hosted turbo and large-v3 even reverses between meetings, so treat them as tied.''')}

## Why Deepgram wins: it drops less speech

{_wrap(f'''Substitutions are almost identical - {a['scores']['deepgram-nova-3']['sub']} against
{a['scores']['groq-turbo']['sub']} on ES2008a - so both models mishear at the same rate. The gap
is deletions: {a['scores']['deepgram-nova-3']['del']} against
{a['scores']['groq-turbo']['del']}. Deepgram recovers words Whisper never emits.''')}

{_wrap('''That refines the limit rather than removing it. Roughly a tenth of the reference words
are spoken while someone else is talking, and a single mixed channel plus a linear transcript
cannot represent them. But the floor is set by segmentation, not model capacity: scaling Whisper
from base to large-v3 never improved deletions, while a model with better voice-activity
handling improved them by a third.''')}

## One mis-heard name reached the task board

{_wrap('''Uploading ES2010a produced seven action items, all traceable to something actually
said. One was assigned to "Vanilla", who does not exist: the participant is **Fenella**, and the
transcriber substituted the name. The parser then used it faithfully.''')}

{_wrap('''This is the concrete cost of transcription error. It also shows where the confidence
score earns its place - the two owners the audio never states scored 65%, while the one named
outright ("the marketing person, that's Courtney") scored 85%.''')}

## Hosted or local

{_wrap('''The local backend is a development convenience, not an alternative. It needs roughly
1.5 GB of RAM that a free-tier instance does not have, and the host's CPU is far slower than a
laptop's: the same ffmpeg transcode measured 0.2s locally and 7.3s on the deployed instance.
Whisper turbo took 212s on a laptop, so on the server it would run into the tens of minutes if
it fit at all. A hosted endpoint is the only option that works there, and it returns in seconds.
The local and hosted times below are therefore two deployments, not two models.''')}

## Appendix A - full figures

ES2008a ({a['scores']['deepgram-nova-3']['ref_words']} reference words, {MEETINGS['ES2008a']['minutes']} min)

| Configuration | WER | 95% CI | Sub | Del | Ins |
|---|---|---|---|---|---|
{detail(a)}

ES2010a ({b['scores']['deepgram-nova-3']['ref_words']} reference words, {MEETINGS['ES2010a']['minutes']} min)

| Configuration | WER | 95% CI | Sub | Del | Ins |
|---|---|---|---|---|---|
{detail(b)}

Intervals come from resampling the reference in 50-word blocks, 2,000 draws, seeded. Paired
comparisons resample both systems on the same blocks:

| Comparison (ES2008a) | Difference, 95% CI | Separable? |
|---|---|---|
{sig(a, keypairs)}

## Appendix B - Whisper model size (ES2008a, local)

| Configuration | WER | Time | Note |
|---|---|---|---|
{ladder}

{_wrap('''Size is not a proxy for quality here. Local large-v3 has twenty times the parameters
of base and scores worse, because it degenerates into hallucination loops: 133 repeated 5-grams
against 26-39 for every other single-channel run. The same weights score 16.4% behind a hosted
endpoint, so this is a property of the local decoding defaults, not of the model.''')}

## Method and limitations

- Reference: the AMI manual transcription (NXT 1.6.2), assembled by
  `python -m eval.build_ami_reference <meeting> --annotations <zip>`, ordered by word start
  time with punctuation and non-speech markup removed.
- Both sides pass through Whisper's `EnglishTextNormalizer`, so British and American spellings
  are not penalised. WER is Levenshtein over the normalised words, split into substitutions,
  deletions and insertions.
- Hosted runs go through the application's own `transcribe_audio()`, so every model receives
  byte-identical audio and the figures describe the product rather than a separate harness.
- **Two meetings, both AMI**, both close-talking headset mixes - the cleanest audio the corpus
  publishes. Laptop-microphone audio in a real room will be worse.
- **Timing is not controlled.** Hosted rows are medians of 3-5 calls including network transfer;
  local rows are single CPU-only runs on an Apple M4.
- **WER is not the product metric.** The output is action items, not words; whether a 13%
  transcript yields a different board from a 17% one is a separate measurement.
"""


def main() -> None:
    argparse.ArgumentParser(description="Score the speech-to-text configurations.").parse_args()
    data = score_all()
    RESULTS.write_text(json.dumps(data, indent=2) + "\n")
    REPORT.write_text(render(data))
    total = sum(len(d["scores"]) for d in data.values())
    print(f"{total} runs scored across {len(data)} meetings")
    print(f"wrote {RESULTS.relative_to(REPO)} and {REPORT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
