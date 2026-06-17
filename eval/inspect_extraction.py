"""Ad-hoc inspection: parse each synthetic transcript and pretty-print the structured
output (decisions + action items with owner, deadline, status, confidence) for manual review.

Usage (repo root, backend venv active, ANTHROPIC_API_KEY in backend/.env):
    python -m eval.inspect_extraction
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
TRANSCRIPTS_DIR = REPO_ROOT / "data" / "synthetic-transcripts"

sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")

from app.llm.parser import TranscriptParser  # noqa: E402

# (file, meeting_date) — date matters so relative deadline cues resolve correctly.
TRANSCRIPTS = [
    ("data-migration-workshop-04.txt", date(2026, 6, 18)),
    ("finance-workshop-01.txt", date(2026, 6, 15)),
    ("logistics-workshop-02.txt", date(2026, 6, 16)),
    ("security-workshop-03.txt", date(2026, 6, 17)),
]

STATUS_ICON = {"done": "[DONE]", "in_progress": "[WIP] ", "todo": "[TODO]"}


def main() -> None:
    parser = TranscriptParser()
    for filename, meeting_date in TRANSCRIPTS:
        text = (TRANSCRIPTS_DIR / filename).read_text()
        result = parser.parse(text, meeting_date=meeting_date)

        print("\n" + "=" * 78)
        print(f"{filename}  (meeting date {meeting_date})")
        print("=" * 78)

        print(f"\nDECISIONS ({len(result.decisions)}):")
        for d in result.decisions:
            print(f"  - {d}")

        items = result.action_items
        counts = {s: sum(1 for i in items if i.status.value == s) for s in ("todo", "in_progress", "done")}
        print(
            f"\nACTION ITEMS ({len(items)}): "
            f"{counts['todo']} todo / {counts['in_progress']} in-progress / {counts['done']} done"
        )
        for i in items:
            owner = i.owner or "(unassigned)"
            deadline = i.deadline.isoformat() if i.deadline else "no deadline"
            icon = STATUS_ICON.get(i.status.value, i.status.value)
            print(f"  {icon} {i.description}")
            print(f"          owner={owner}  deadline={deadline}  conf={i.confidence:.2f}")


if __name__ == "__main__":
    main()
