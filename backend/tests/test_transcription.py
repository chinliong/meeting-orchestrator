"""Formatting of Deepgram's speaker-labelled transcript (app/llm/transcription.py)."""
from app.llm.transcription import _speaker_turns


def test_speaker_turns_labels_and_joins_consecutive_utterances():
    results = {"utterances": [
        {"speaker": 0, "transcript": "Morning, everyone."},
        {"speaker": 0, "transcript": "Let's start."},
        {"speaker": 1, "transcript": "I'll send the file by Friday."},
        {"speaker": 0, "transcript": "Thanks, Priya."},
    ]}
    assert _speaker_turns(results) == (
        "Speaker 1: Morning, everyone. Let's start.\n"
        "Speaker 2: I'll send the file by Friday.\n"
        "Speaker 1: Thanks, Priya."
    )


def test_speaker_turns_is_none_without_utterances():
    # The caller then returns Deepgram's plain transcript instead.
    assert _speaker_turns({}) is None
    assert _speaker_turns({"utterances": [{"speaker": 0, "transcript": "  "}]}) is None
