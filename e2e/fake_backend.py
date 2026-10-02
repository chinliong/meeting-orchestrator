"""The real backend with every paid or external call replaced, for the browser suites.

The extraction, summary and subtask models, the transcription service and email are all
simulated, and the API keys are blanked, so nothing is charged. The fakes react to words in the
transcript so a suite can choose what happens:

    SLOW        the extraction takes 5 s
    BROKEN      the extraction fails as a model outage would
    LOWCONF     one low-confidence task
    UNASSIGNED  three tasks with no owner
    SUMFAIL     the meeting summary fails
    (otherwise) two tasks, owned by Daniel and Priya

A recording "transcribes" in 6 s to a SLOW transcript. DATABASE_URL and E2E_PORT come from the
environment (e2e/run.py sets them); rate limits stay as configured there.
"""
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
os.environ.setdefault("CORS_ORIGINS", "*")
# Blank every key before the app loads backend/.env (which never overrides a variable already set),
# so no request can reach a paid service even if a fake below were missed.
for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "DEEPGRAM_API_KEY",
            "BREVO_API_KEY", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
    os.environ[key] = ""
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from app.llm import parser, transcription  # noqa: E402
from app.llm import subtasks as subtasks_module  # noqa: E402
from app.llm import summary as summary_module  # noqa: E402
from app.schemas.schemas import (  # noqa: E402
    ExtractedActionItem,
    ExtractionResult,
    MeetingSummary,
)


def fake_parse(self, text, meeting_date=None):
    if "SLOW" in text:
        time.sleep(5)
    if "BROKEN" in text:
        raise RuntimeError("Gemini HTTP 503: model temporarily unavailable")
    if "LOWCONF" in text:
        return ExtractionResult(decisions=[], action_items=[
            ExtractedActionItem(description="Maybe ask finance about the accruals", owner="Priya", confidence=0.5)])
    if "UNASSIGNED" in text:
        return ExtractionResult(decisions=[], action_items=[
            ExtractedActionItem(description=f"Unassigned job {i}") for i in range(3)])
    return ExtractionResult(decisions=[], action_items=[
        ExtractedActionItem(description="Finish APAC mapping", owner="Daniel"),
        ExtractedActionItem(description="Confirm cost codes", owner="Priya")])


def fake_transcribe(path):
    time.sleep(6)
    return "SLOW audio transcript"


def fake_summarise(text, title, meeting_date):
    time.sleep(1.5)
    if "SUMFAIL" in text:
        raise RuntimeError("Gemini HTTP 503")
    return MeetingSummary(overview=f"The team met for {title} to review the APAC mapping and the bank file "
                                   "tests. They agreed to align the ledger cutover with the mapping.")


parser.TranscriptParser.parse = fake_parse
transcription.is_available = lambda: True
transcription.transcribe_file = fake_transcribe
summary_module.summarise = fake_summarise
subtasks_module.SubtaskGenerator.generate = lambda self, task, instructions=None: ["Draft the plan", "Review it"]

if __name__ == "__main__":
    import uvicorn
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("E2E_PORT", "8000")), log_level="warning")
