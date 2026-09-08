from __future__ import annotations

import os
from datetime import date

import logging
import time

import anthropic

from app.schemas.schemas import ExtractionResult

EXTRACTION_TOOL = {
    "name": "record_extraction",
    "description": "Record the decisions and action items extracted from a meeting transcript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key decisions made during the meeting, one sentence each.",
            },
            "action_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "What needs to be done.",
                        },
                        "owner": {
                            "type": ["string", "null"],
                            "description": "The named stakeholder responsible. Null if not stated.",
                        },
                        "deadline": {
                            "type": ["string", "null"],
                            "description": (
                                "ISO 8601 date (YYYY-MM-DD) inferred from contextual cues "
                                "(e.g. 'by next Friday'). Null if no deadline is implied."
                            ),
                        },
                        "status": {
                            "type": "string",
                            "enum": ["todo", "in_progress", "done"],
                            "description": (
                                "Current status inferred from the transcript. Use 'done' if the "
                                "work is described as finished/completed/confirmed; 'in_progress' "
                                "if it is being worked on, partially complete, or currently "
                                "running; 'todo' if it is not started yet. Default to 'todo' "
                                "when no status cue is present."
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "description": "0-1 confidence that this is a genuine action item.",
                        },
                        "source_decision": {
                            "type": ["string", "null"],
                            "description": "The decision or discussion this action item stems from, quoted "
                                           "or briefly paraphrased. Fill this "
                                           "whenever the origin is identifiable "
                                           "in the transcript; null only when it "
                                           "genuinely is not.",
                        },
                    },
                    "required": ["description", "status", "confidence"],
                },
            },
        },
        "required": ["decisions", "action_items"],
    },
}

SYSTEM_PROMPT = """You are an assistant that extracts structured project-management data from \
raw, possibly messy meeting transcripts. Identify key decisions and concrete action items.

For each action item:
- Assign an owner only if a named person is clearly responsible; otherwise leave it null.
- Infer a deadline from contextual cues (e.g. "by Friday", "before go-live", "next week") \
relative to the meeting date provided. If no cue exists, leave the deadline null.
- Determine the status from the transcript: "done" if the work is described as finished, \
completed, or confirmed; "in_progress" if it is being worked on, partially complete, or \
currently running; "todo" if it has not been started. Default to "todo" when there is no cue.
- Record the decision or discussion the item stems from in source_decision. This is what lets a \
task on the board be traced back to the meeting, so fill it whenever the transcript makes the \
origin identifiable; leave it null only when the item genuinely has no identifiable source.
- Do not invent action items that are not implied by the transcript.
- Give a confidence score reflecting how explicit the transcript was about this item.

Always respond by calling the record_extraction tool."""


# Which model family runs the extraction. Gemini is the default because it leads Claude Sonnet
# on recall, precision and F1 over eight runs, each separated by an exact permutation test - see
# docs/evaluation-report.md. Set LLM_PROVIDER=anthropic to fall back to Claude; both backends
# receive the same system prompt, the same tool schema and the same user turn, so the only
# variable is the model.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

# uvicorn configures this logger at INFO, so these lines show up in the Render logs.
log = logging.getLogger("uvicorn.error")


class TranscriptParser:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        provider: str | None = None,
    ):
        self.provider = (provider or LLM_PROVIDER).strip().lower()
        # Fall back rather than fail: a deployment that selects Gemini but has no Gemini key
        # would otherwise 500 on every upload. Claude produces a slightly weaker extraction,
        # which is a better outcome than none, and the log line says the switch happened.
        if self.provider == "gemini" and not os.getenv("GEMINI_API_KEY"):
            if os.getenv("ANTHROPIC_API_KEY"):
                logging.getLogger("uvicorn.error").warning(
                    "parser: GEMINI_API_KEY is not set - falling back to Claude")
                self.provider = "anthropic"
        self.model = model or (
            os.getenv("GEMINI_MODEL") if self.provider == "gemini"
            else os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"))
        # Overridable so the evaluation harness can compare prompt variants.
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        # The Anthropic client is only constructed when it is the selected backend, so a
        # Gemini-only deployment does not need ANTHROPIC_API_KEY set.
        self.client = (anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
                       if self.provider != "gemini" else None)

    def _resolved_model(self) -> str:
        """The model a parse will actually use, including the client-side default.

        `self.model` is None when no override is set, so logging it directly would say
        "default" rather than naming what ran. The deployed logs are the only record of which
        model produced a given board, so they name it.
        """
        if self.model:
            return self.model
        if self.provider == "gemini":
            from app.llm import gemini
            return gemini.DEFAULT_MODEL
        return "claude-sonnet-4-6"

    def parse(self, transcript_text: str, meeting_date: date | None = None) -> ExtractionResult:
        meeting_date = meeting_date or date.today()
        started = time.perf_counter()
        if self.provider == "gemini":
            from app.llm import gemini
            args = gemini.call_tool(
                self.system_prompt, EXTRACTION_TOOL,
                gemini.user_text(transcript_text, meeting_date), model=self.model)
        else:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                tools=[EXTRACTION_TOOL],
                tool_choice={"type": "tool", "name": "record_extraction"},
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Meeting date: {meeting_date.isoformat()}\n\n"
                            f"Transcript:\n{transcript_text}"
                        ),
                    }
                ],
            )
            args = next(b for b in message.content if b.type == "tool_use").input
        log.info("parser: %s %s %.1fs", self.provider, self._resolved_model(),
                 time.perf_counter() - started)
        return ExtractionResult.model_validate(args)


def parse_transcript(transcript_text: str, meeting_date: date | None = None) -> ExtractionResult:
    """Convenience entrypoint: raw transcript text in, structured ExtractionResult out."""
    return TranscriptParser().parse(transcript_text, meeting_date)
