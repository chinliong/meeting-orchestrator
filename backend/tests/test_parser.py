"""Unit test for TranscriptParser: the Anthropic client is faked so no network/key is needed."""
from datetime import date
from types import SimpleNamespace

from app.llm.parser import TranscriptParser


def test_parse_extracts_tool_use(monkeypatch):
    tool_block = SimpleNamespace(
        type="tool_use",
        input={
            "decisions": ["Go big-bang."],
            "action_items": [
                {"description": "Finalize mapping", "owner": "Daniel", "deadline": "2026-06-19", "confidence": 0.9},
                {"description": "Unowned cleanup", "confidence": 0.4},
            ],
        },
    )
    fake_message = SimpleNamespace(content=[SimpleNamespace(type="text"), tool_block])

    parser = TranscriptParser(api_key="test-key")
    monkeypatch.setattr(parser.client.messages, "create", lambda **kwargs: fake_message)

    result = parser.parse("transcript", meeting_date=date(2026, 6, 18))

    assert result.decisions == ["Go big-bang."]
    assert len(result.action_items) == 2
    first = result.action_items[0]
    assert first.owner == "Daniel"
    assert first.deadline == date(2026, 6, 19)
    # Defaults applied for the minimal second item.
    assert result.action_items[1].owner is None
    assert result.action_items[1].confidence == 0.4
