"""Unit tests for TranscriptParser. Both backends are faked, so no network or key is needed."""
from datetime import date
from types import SimpleNamespace

from app.llm.parser import TranscriptParser
from app.models.models import TaskStatus


def test_parse_extracts_tool_use_anthropic(monkeypatch):
    tool_block = SimpleNamespace(
        type="tool_use",
        input={
            "decisions": ["Go big-bang."],
            "action_items": [
                {"description": "Finalize mapping", "owner": "Daniel", "deadline": "2026-06-19", "status": "in_progress", "confidence": 0.9},
                {"description": "Unowned cleanup", "confidence": 0.4},
            ],
        },
    )
    fake_message = SimpleNamespace(content=[SimpleNamespace(type="text"), tool_block])

    parser = TranscriptParser(api_key="test-key", provider="anthropic")
    monkeypatch.setattr(parser.client.messages, "create", lambda **kwargs: fake_message)

    result = parser.parse("transcript", meeting_date=date(2026, 6, 18))

    assert result.decisions == ["Go big-bang."]
    assert len(result.action_items) == 2
    first = result.action_items[0]
    assert first.owner == "Daniel"
    assert first.deadline == date(2026, 6, 19)
    assert first.status == TaskStatus.IN_PROGRESS
    # Defaults applied for the minimal second item.
    assert result.action_items[1].owner is None
    assert result.action_items[1].confidence == 0.4
    assert result.action_items[1].status == TaskStatus.TODO


def test_parse_extracts_function_call_gemini(monkeypatch):
    """The Gemini backend is the shipped default, so it needs the same guarantee.

    Both providers must return an identical ExtractionResult from equivalent payloads - the
    schema contract is what makes the two interchangeable.
    """
    args = {
        "decisions": ["Go big-bang."],
        "action_items": [
            {"description": "Finalize mapping", "owner": "Daniel", "deadline": "2026-06-19",
             "status": "in_progress", "confidence": 0.9},
            {"description": "Unowned cleanup", "confidence": 0.4},
        ],
    }
    seen = {}

    def fake_call_tool(system_prompt, tool, user_text, model=None):
        seen["user_text"] = user_text
        seen["tool"] = tool["name"]
        return args

    monkeypatch.setattr("app.llm.gemini.call_tool", fake_call_tool)

    parser = TranscriptParser(provider="gemini")
    result = parser.parse("transcript", meeting_date=date(2026, 6, 18))

    # The meeting date must reach the model - relative deadline cues resolve against it.
    assert "Meeting date: 2026-06-18" in seen["user_text"]
    assert seen["tool"] == "record_extraction"
    assert result.decisions == ["Go big-bang."]
    assert result.action_items[0].deadline == date(2026, 6, 19)
    assert result.action_items[0].status == TaskStatus.IN_PROGRESS
    assert result.action_items[1].owner is None
    assert result.action_items[1].status == TaskStatus.TODO


def test_gemini_is_the_default_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert TranscriptParser().provider == "gemini"
