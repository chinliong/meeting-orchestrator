"""A short AI overview of one meeting, so someone looking at the board has the context behind its tasks.

This is a separate request made after extraction, never part of it. The extraction prompt and
schema stay exactly as they were evaluated (docs/evaluation-report.md), and a summary that fails
cannot affect a meeting's tasks. The summary itself is not evaluated, so the app labels it as
an AI summary.

It describes the meeting as it happened, not the current state of the work: the tasks on the
board move on after the meeting, and a summary claiming what is still open would go out of date.

Like app/llm/parser.py, it forces a structured response through a Gemini function call.
"""
from __future__ import annotations

import logging
import time
from datetime import date

from app.llm import gemini
from app.schemas.schemas import MeetingSummary

# uvicorn configures this logger at INFO, so these lines show up in the Render logs.
log = logging.getLogger("uvicorn.error")

SUMMARY_TOOL = {
    "name": "record_meeting_summary",
    "description": "Record a short overview of the meeting.",
    "input_schema": {
        "type": "object",
        "properties": {
            "overview": {
                "type": "string",
                "description": (
                    "Two to four plain sentences, in the past tense, on what the meeting was about: "
                    "its purpose, the main topics discussed and anything it agreed. No bullet points."
                ),
            },
        },
        "required": ["overview"],
    },
}

SYSTEM_PROMPT = """You write a short overview of a project meeting for someone who was not \
there, so they understand the context behind the tasks that came out of it.

Guidelines:
- Say what the meeting was for, the main topics discussed and anything it agreed.
- Write two to four plain sentences in the past tense, describing the meeting as it happened. \
Do not describe the current state of the work or say what is still outstanding, since that \
changes after the meeting.
- Report only what the transcript says. Do not add advice, opinions or anything not discussed.
- Use people's names as they appear in the transcript.
- Do not list the individual tasks; they are shown separately.

Always respond by calling the record_meeting_summary tool."""


def summarise(transcript_text: str, title: str, meeting_date: date) -> MeetingSummary:
    """Write an overview of one meeting's transcript. Raises if the model fails or returns none."""
    user_content = f"Meeting: {title}\n{gemini.user_text(transcript_text, meeting_date)}"
    started = time.perf_counter()
    args = gemini.call_tool(SYSTEM_PROMPT, SUMMARY_TOOL, user_content)
    log.info("summary: gemini %.1fs", time.perf_counter() - started)
    overview = args.get("overview")
    if not isinstance(overview, str) or not overview.strip():
        raise gemini.GeminiError("the model returned an empty summary")
    return MeetingSummary(overview=overview.strip())
