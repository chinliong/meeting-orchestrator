# Architecture

## High-level flow

1. User submits a meeting transcript (text, or audio/video for optional Whisper path) via
   the Next.js frontend.
2. Frontend calls the FastAPI backend's transcript submission endpoint.
3. Backend (optionally) runs the audio through Whisper to obtain text, then sends the
   transcript to the LLM with a structured-output prompt.
4. LLM response is parsed/validated (e.g. via Pydantic) into decisions, action items,
   owners, and deadlines.
5. Structured data is persisted to the relational database (tasks, projects, stakeholders).
6. Frontend polls/fetches the task list and renders the Kanban board, with filtering by
   owner and deadline.

## Components

- **Frontend (Next.js/React):** Kanban board, task detail view, filters, transcript upload UI.
- **Backend (FastAPI):**
  - `POST /transcripts` — submit raw transcript (or audio) for processing.
  - `GET /tasks` — list tasks, with filters.
  - `PATCH /tasks/{id}` — update task status/owner/deadline.
  - `GET /projects` — list projects/meetings.
  - LLM parsing module (reusable, framework-agnostic Python module).
- **Database:** PostgreSQL (prod) / SQLite (dev). Tables: `projects`, `meetings`,
  `stakeholders`, `tasks`.
- **LLM provider:** Claude (Anthropic) / Gemini / Mistral — via API, structured output.
- **Speech-to-text (optional):** OpenAI Whisper, run as a pre-processing step before the
  transcript reaches the LLM parsing module.

## Diagram

_TODO: insert architecture diagram (e.g. draw.io / Mermaid) once component boundaries
are finalised._
