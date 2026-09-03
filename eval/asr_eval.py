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
REFERENCE = REPO / "data" / "test-audio" / "ES2008a.reference.words.txt"
RESULTS = REPO / "eval" / "asr_results.json"
REPORT = REPO / "docs" / "asr-evaluation.md"
AUDIO_SECONDS = 1043.0          # ES2008a.Mix-Headset.wav, 17.4 minutes
BOOTSTRAP_BLOCK = 50            # reference words per resampled block
BOOTSTRAP_N = 2000              # resamples; seeded, so the intervals are reproducible


@dataclass(frozen=True)
class Backend:
    label: str
    seconds: float | None = None    # wall-clock for the full recording, single measurement;
    note: str = ""                  # None means read it from the .timing.json sidecar


# Wall-clock timings are single measurements on one machine, so they rank configurations but do
# not support fine-grained claims - see the limitations in the report.
BACKENDS = {
    "turbo":            Backend("Whisper turbo", 212),
    "medium":           Backend("Whisper medium", 198),
    "small":            Backend("Whisper small", 78),
    "base":             Backend("Whisper base", 33,
                                note="the configured default before this evaluation"),
    "large-v3":         Backend("Whisper large-v3", 623,
                                note="hallucination loops: 133 repeated 5-grams against 26-39 "
                                     "for every other single-channel configuration - see below, "
                                     "the same weights score 16.4% when hosted"),
    "perchannel-turbo": Backend("Whisper turbo, per-channel", 470,
                                note="four headset channels transcribed separately and merged; "
                                     "microphone bleed duplicates most speech"),
    # Hosted endpoints, timed by eval.asr_transcribe through the application's own upload path.
    "groq-turbo":       Backend("Groq whisper-large-v3-turbo (hosted)",
                                note="the configured default: nothing runs on the server, so the "
                                     "audio path fits a memory-limited free tier"),
    "groq-large-v3":    Backend("Groq whisper-large-v3 (hosted)",
                                note="nominally ahead of hosted turbo but inside the interval, "
                                     "and 1.9x the wall-clock"),
}


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


def score_all() -> dict:
    norm = EnglishTextNormalizer()
    ref = norm(REFERENCE.read_text()).split()
    out, errors = {}, {}
    for key, b in BACKENDS.items():
        f = TRANSCRIPTS / f"ES2008a.{key}.txt"
        if not f.exists():
            continue
        timing = TRANSCRIPTS / f"ES2008a.{key}.timing.json"
        seconds = json.loads(timing.read_text())["seconds"] if timing.exists() else b.seconds
        if seconds is None:
            continue
        hyp = norm(f.read_text()).split()
        r = wer(ref, hyp)
        r.update(label=b.label, seconds=seconds, note=b.note,
                 realtime_factor=round(AUDIO_SECONDS / seconds, 1))
        out[key] = r
        errors[key] = per_ref_errors(ref, hyp)

    stats = bootstrap(errors)
    for key, r in out.items():
        r["ci"] = stats["ci"][key]
    return out, stats["pairs"]


def _wrap(text: str, width: int = 96) -> str:
    return "\n\n".join(textwrap.fill(" ".join(p.split()), width)
                       for p in text.strip().split("\n\n"))


def render(scores: dict, pairs: dict) -> str:
    rows = sorted(scores.values(), key=lambda v: v["wer"])
    best = rows[0]["label"]
    table = "\n".join(
        f"| {'**' if v['label'] == best else ''}{v['label']}"
        f"{'**' if v['label'] == best else ''} | {v['wer']:.1%} | "
        f"[{v['ci'][0]:.1%}, {v['ci'][1]:.1%}] | {v['sub']} | {v['del']} | "
        f"{v['ins']} | {v['seconds']:.0f}s | {v['realtime_factor']:.0f}x |" for v in rows)
    sig = "\n".join(
        f"| {k} | {v['lo']:+.1%} to {v['hi']:+.1%} | "
        f"{'**yes**' if v['significant'] else 'no'} |"
        for k, v in pairs.items()
        if k in ("groq-turbo vs turbo", "groq-large-v3 vs groq-turbo",
                 "groq-turbo vs medium", "base vs turbo"))
    notes = "\n".join(f"- **{v['label']}** - {v['note']}" for v in rows if v["note"])

    return f"""# Speech-to-Text Evaluation

_Generated by `python -m eval.asr_eval` on {date.today().isoformat()}. Re-run to refresh._

## The decision

The audio path runs a **hosted Whisper endpoint** (Groq, `whisper-large-v3-turbo`), falling
back to a **local Whisper model** when no key is configured. The local fallback is **turbo**.

{_wrap('''The decisive argument is deployability, not accuracy. The hosted endpoint keeps the
model off the server, and the local fallback needs roughly 1.5 GB of RAM that a free-tier
instance does not have - so hosted is the only backend that can actually serve this
application. On accuracy it is a tie: 16.6% against 17.5% for the best local configuration, a
gap the bootstrap below cannot separate from sampling noise on a single recording. The fair
claim is that moving to the hosted endpoint costs nothing in accuracy while removing the
memory requirement.''')}

{_wrap('''Between the two hosted models, `large-v3` scores 16.4% against turbo's 16.6% - again
inside the noise - so turbo is the default on the tiebreak of running 1.8x faster. The local
fallback is set to turbo, which reaches 17.5% against 28.8% for base; that gap is large enough
to be real.''')}

## Results

Scored against the AMI manual transcript for ES2008a ({rows[0]['ref_words']} normalised
reference words, 17.4 minutes, four speakers).

| Configuration | WER | 95% CI | Sub | Del | Ins | Time | Speed |
|---|---|---|---|---|---|---|---|
{table}

{notes}

## The same weights score 33.1% locally and 16.4% hosted

{_wrap('''The sharpest result in the table is that `large-v3` appears twice, sixteen points
apart, running the same published weights. The local run fails by hallucination: its output
contains 133 repeated 5-grams against 26 to 39 for every other single-channel configuration,
including runs of repeated punctuation and one phrase emitted eight times. The hosted run of
the same model contains 35, which is the normal range.''')}

{_wrap('''The difference is therefore not in the weights but in what surrounds them - voice
activity detection, how the audio is segmented, and whether decoding retries a segment when it
degenerates. A hosted endpoint ships that scaffolding; `whisper.load_model(...).transcribe(...)`
at its defaults does not. The practical lesson is that a bare local run understates what a model
can do, so "large-v3 is worse than base" was a property of the local configuration and not of
the model.''')}

## How much these numbers support

{_wrap('''Every figure comes from one 17-minute recording, so the differences at the top of the
table are smaller than the uncertainty. Resampling the reference in blocks of 50 words (2,000
draws, seeded) gives the intervals above and the paired comparisons below. Paired means both
systems are scored on the same resampled audio each draw, which is the right test for "is A
better than B" - comparing two independent intervals would understate the evidence.''')}

| Comparison | Difference, 95% CI | Separable? |
|---|---|---|
{sig}

{_wrap('''So the ranking is only partly real. Hosted turbo, hosted large-v3 and local turbo are
statistically indistinguishable on this recording: the honest statement is that they tie. The
larger gaps - hosted turbo against medium, and turbo against base - hold up. Choosing the
hosted endpoint therefore rests on memory and latency, which are not in doubt, rather than on
an accuracy win that this evaluation cannot demonstrate.''')}

## Is hosted versus local a fair comparison?

{_wrap('''For accuracy, yes. Both read the same recording, are scored against the same
reference with the same normaliser, and the audio the endpoint receives is 16 kHz mono FLAC -
lossless, and the same resampling Whisper applies internally - so no information is lost that
the local run keeps.''')}

{_wrap('''For speed, no, and the table should be read with that in mind. The local times are
CPU-only on an Apple M4; `whisper.load_model` selects CUDA or CPU and never the Metal backend,
so the machine's GPU sat idle. The hosted times are a datacentre inference accelerator plus
network transfer from a home connection. The comparison measures two deployments, not two
models. It is still the number that matters for the product - a user waits 2 seconds instead of
3.5 minutes - but it is not evidence that one model is faster than another.''')}

{_wrap('''One further caveat applies to accuracy. Hosted and local turbo run the same published
weights, so their 0.9-point difference is not a difference between models at all; it is a
difference between decoding stacks. The `large-v3` rows make this unmistakable - sixteen points
apart on identical weights.''')}

## What limits every configuration

{_wrap('''Deletions dominate the error profile and barely improve with model size: 332 at base,
290 at small, 311 at medium. Measuring the reference transcript explains why. **9.4% of the
reference words (236 of 2,506) are spoken while another participant is also speaking.** The
mixed recording collapses four microphones into one waveform and a transcript is linear, so
overlapping speech cannot be represented at all. That sets a floor no amount of model capacity
reaches.''')}

{_wrap('''Transcribing the four individual headset channels separately was tested as a way to
remove the limit. It recovered deletions as predicted, 237 down to 182, but microphone bleed
means every channel also captures the other three speakers: the merged transcript repeated
phrases four times, added 1,315 insertions and scored 66.9%. Recovering overlapped speech needs
speaker-activity gating, not simply more audio channels.''')}

## Limitations

- **One meeting.** Every figure comes from AMI ES2008a, and the bootstrap above measures
  sampling within that recording only. It cannot capture variation between meetings, speakers,
  accents or recording conditions, which is likely the larger source of uncertainty. Separating
  the top three configurations would need several more meetings, not more resamples of this one.
- **Timing is not a controlled comparison.** Local rows are single CPU-only runs on an Apple M4;
  hosted rows are the median of five calls including network transfer (turbo 1.9-2.5s,
  large-v3 4.0-4.9s; both returned byte-identical transcripts every run). See the fairness
  section above.
- **Best-case audio.** The headset mix is the cleanest recording AMI publishes, with a
  close-talking microphone per speaker. Laptop-microphone audio in a real room will be worse.
- **Word error rate is not the product metric.** The system's output is action items, not words.
  Whether a 16.6% transcript yields a different board from a 28.8% one is a separate
  measurement, not yet made.

## Method

- Reference: the AMI manual transcription (NXT release 1.6.2), assembled from the four
  per-speaker word files, ordered by start time, with punctuation and the non-speech
  `vocalsound`, `disfmarker` and `gap` elements removed.
- Both reference and hypothesis pass through Whisper's `EnglishTextNormalizer`, which reconciles
  British and American spellings so a model is not penalised for "color" where AMI wrote
  "colour".
- Word error rate is Levenshtein distance over the normalised word sequences, reported with its
  substitution, deletion and insertion split so the failure mode is visible rather than only the
  total.
- The hosted configurations are produced by `python -m eval.asr_transcribe groq-turbo`, which
  calls the application's own `transcribe_audio()`. The compression, upload cap and API call are
  the deployed code paths, so the figures describe the product and not a separate harness.
- Transcripts are cached in `eval/asr_transcripts/`; scoring re-runs offline.
  `eval/asr_results.json` holds the scored figures, `.timing.json` sidecars the measured
  wall-clock for the hosted runs.
"""


def main() -> None:
    argparse.ArgumentParser(description="Score the speech-to-text configurations.").parse_args()
    scores, pairs = score_all()
    RESULTS.write_text(json.dumps({"scores": scores, "pairs": pairs}, indent=2) + "\n")
    REPORT.write_text(render(scores, pairs))
    print(f"{len(scores)} configurations scored")
    print(f"wrote {RESULTS.relative_to(REPO)} and {REPORT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
