from __future__ import annotations

import os
from datetime import date

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
                        "confidence": {
                            "type": "number",
                            "description": "0-1 confidence that this is a genuine action item.",
                        },
                        "source_decision": {
                            "type": ["string", "null"],
                            "description": "The decision or context this action item stems from, if any.",
                        },
                    },
                    "required": ["description", "confidence"],
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
- Do not invent action items that are not implied by the transcript.
- Give a confidence score reflecting how explicit the transcript was about this item.

Always respond by calling the record_extraction tool."""


class TranscriptParser:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    def parse(self, transcript_text: str, meeting_date: date | None = None) -> ExtractionResult:
        meeting_date = meeting_date or date.today()
        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
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

        tool_use = next(block for block in message.content if block.type == "tool_use")
        return ExtractionResult.model_validate(tool_use.input)


def parse_transcript(transcript_text: str, meeting_date: date | None = None) -> ExtractionResult:
    """Convenience entrypoint: raw transcript text in, structured ExtractionResult out."""
    return TranscriptParser().parse(transcript_text, meeting_date)
