"""LLM-powered breakdown of a single action item into a checklist of subtasks.

Two modes, mirroring the UI's "Generate" menu:
- *from task details* — decompose the task using only its own context (description, owner,
  deadline, source meeting/decision).
- *from your instructions* — the same, but steered by free-text instructions the user typed.

Like app/llm/parser.py, this uses Anthropic tool-use to force a structured (JSON) response.
"""
from __future__ import annotations

import os

import anthropic

from app.models.models import Task

MAX_SUBTASKS = 8

SUBTASK_TOOL = {
    "name": "record_subtasks",
    "description": "Record the ordered list of subtasks that break the parent task down.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subtasks": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Concrete, actionable steps to complete the parent task, in the order they "
                    "should be done. Each is a short imperative phrase (about 3-10 words), with no "
                    "numbering or leading punctuation. Return between 2 and "
                    f"{MAX_SUBTASKS} items."
                ),
            }
        },
        "required": ["subtasks"],
    },
}

SYSTEM_PROMPT = """You break a single project action item down into a short checklist of \
concrete subtasks.

Guidelines:
- Each subtask is one clear, actionable step phrased as a short imperative (e.g. "Draft the \
migration plan", not "The migration plan should be drafted").
- Order them the way they would naturally be carried out.
- Keep them specific to THIS task; do not invent unrelated work or restate the task verbatim.
- Prefer 3-6 subtasks. Never return more than {max}.
- If the user gives extra instructions, follow them.

Always respond by calling the record_subtasks tool.""".format(max=MAX_SUBTASKS)


def _task_context(task: Task) -> str:
    """A compact description of the task for the model to break down."""
    lines = [f"Task: {task.description}"]
    if task.owner:
        lines.append(f"Owner: {task.owner}")
    if task.deadline:
        lines.append(f"Deadline: {task.deadline.isoformat()}")
    if task.source_decision:
        lines.append(f"Stems from decision: {task.source_decision}")
    if task.meeting_title:
        lines.append(f"From meeting: {task.meeting_title}")
    if task.project is not None and task.project.name:
        lines.append(f"Project: {task.project.name}")
    existing = [s.title for s in task.subtasks]
    if existing:
        lines.append("Existing subtasks (do not repeat these): " + "; ".join(existing))
    return "\n".join(lines)


class SubtaskGenerator:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    def generate(self, task: Task, instructions: str | None = None) -> list[str]:
        user_content = _task_context(task)
        if instructions and instructions.strip():
            user_content += f"\n\nUser instructions for the breakdown:\n{instructions.strip()}"

        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[SUBTASK_TOOL],
            tool_choice={"type": "tool", "name": "record_subtasks"},
            messages=[{"role": "user", "content": user_content}],
        )

        tool_use = next(block for block in message.content if block.type == "tool_use")
        raw = tool_use.input.get("subtasks", [])
        # Defensive tidy-up: drop blanks, trim, and cap the count.
        titles = [t.strip() for t in raw if isinstance(t, str) and t.strip()]
        return titles[:MAX_SUBTASKS]
