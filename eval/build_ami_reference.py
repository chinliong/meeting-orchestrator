"""Assemble a reference transcript from the AMI manual annotations (Objective 4).

The AMI corpus stores one word file per speaker, each word carrying a start time. A reference
for word error rate needs a single linear transcript, so the per-speaker files are merged and
ordered by start time.

    python -m eval.build_ami_reference ES2010a --annotations ami_public_manual_1.6.2.zip

Writes two files next to the audio:
    <id>.reference.txt        speaker-labelled turns, for reading and for measuring overlap
    <id>.reference.words.txt  the flat word sequence that eval.asr_eval scores against

Non-speech markup (vocalsound, disfmarker, gap) is dropped from both files. Punctuation is kept
in the readable turn file but dropped from the scored word file, along with case: a
speech-to-text model is not asked to reproduce the annotators' punctuation, so scoring it would
punish the model for the annotation scheme rather than for mishearing. Whisper's
EnglishTextNormalizer folds case anyway, so lowercasing here only keeps the artefact tidy.
"""
from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "data" / "test-audio"
SPEAKERS = "ABCDE"


def load_words(zf: zipfile.ZipFile, meeting: str) -> list[tuple[float, str, str, bool]]:
    """(starttime, speaker, token, is_punctuation) for every token, across all speaker files.

    Ordered by start time, which is what turns four parallel per-speaker files into the single
    linear transcript a word error rate needs.
    """
    words: list[tuple[float, str, str, bool]] = []
    for spk in SPEAKERS:
        name = f"words/{meeting}.{spk}.words.xml"
        if name not in zf.namelist():
            continue
        root = ET.fromstring(zf.read(name).decode("iso-8859-1"))
        for el in root:
            # <vocalsound>, <disfmarker> and <gap> are separate tags, so this keeps speech only.
            if el.tag.split("}")[-1] != "w":
                continue
            text = (el.text or "").strip()
            if not text:
                continue
            words.append((float(el.get("starttime", 0.0)), spk, text,
                          el.get("punc") == "true"))
    words.sort(key=lambda w: w[0])
    return words


def overlap_fraction(zf: zipfile.ZipFile, meeting: str) -> tuple[int, int]:
    """How many reference words are spoken while another speaker is also speaking.

    This is the floor the mixed single-channel recording imposes: a linear transcript cannot
    represent two people talking at once, so those words are unrecoverable by any model.
    """
    spans: dict[str, list[tuple[float, float]]] = {}
    for spk in SPEAKERS:
        name = f"words/{meeting}.{spk}.words.xml"
        if name not in zf.namelist():
            continue
        root = ET.fromstring(zf.read(name).decode("iso-8859-1"))
        spans[spk] = [(float(e.get("starttime", 0)), float(e.get("endtime", 0)))
                      for e in root
                      if e.tag.split("}")[-1] == "w" and e.get("punc") != "true"
                      and (e.text or "").strip() and e.get("starttime") and e.get("endtime")]
    total = overlapped = 0
    for spk, ws in spans.items():
        others = [s for o, ss in spans.items() if o != spk for s in ss]
        others.sort()
        for st, en in ws:
            total += 1
            if any(os_ < en and oe > st for os_, oe in others):
                overlapped += 1
    return overlapped, total


def main() -> None:
    ap = argparse.ArgumentParser(description="Build an AMI reference transcript.")
    ap.add_argument("meeting", help="meeting id, e.g. ES2010a")
    ap.add_argument("--annotations", required=True, help="path to ami_public_manual_1.6.2.zip")
    args = ap.parse_args()

    with zipfile.ZipFile(args.annotations) as zf:
        words = load_words(zf, args.meeting)
        if not words:
            raise SystemExit(f"No word files for {args.meeting} in {args.annotations}")
        overlapped, total = overlap_fraction(zf, args.meeting)

    # Readable turns: consecutive tokens from one speaker, punctuation attached to the word
    # before it rather than spaced off.
    turns, cur, spk = [], "", words[0][1]
    for _, s, w, punc in words:
        if s != spk:
            turns.append(f"Speaker {spk}: {cur}")
            cur, spk = "", s
        cur += w if (punc or not cur) else " " + w
    turns.append(f"Speaker {spk}: {cur}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{args.meeting}.reference.txt").write_text("\n".join(turns) + "\n")
    spoken = [w for _, _, w, punc in words if not punc]
    (OUT_DIR / f"{args.meeting}.reference.words.txt").write_text(
        " ".join(spoken).lower() + "\n")

    span = words[-1][0] - words[0][0]
    print(f"{args.meeting}: {len(spoken)} words, {len(turns)} turns, "
          f"{len({s for _, s, _, _ in words})} speakers, ~{span / 60:.1f} min of speech")
    print(f"  overlapped words: {overlapped}/{total} ({overlapped / total:.1%})")
    print(f"  wrote {args.meeting}.reference.txt and {args.meeting}.reference.words.txt")


if __name__ == "__main__":
    main()
