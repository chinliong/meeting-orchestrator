# AI-Powered Meeting & Workflow Orchestrator

A full-stack web application that turns raw, messy meeting transcripts into structured,
trackable project work. It uses a Large Language Model (Claude) to extract **decisions** and
**action items** — with owners, inferred deadlines, and confidence scores — and presents them
on an auto-generated Kanban board. An optional Whisper speech-to-text layer accepts audio/video
recordings for end-to-end processing.

> ICT4011 Capstone Project.

## Features

- **Transcript parsing** — paste raw meeting text; the LLM returns structured decisions and
  action items via a forced tool-use schema (validated with Pydantic).
- **Owner & deadline inference** — owners assigned only when explicitly stated; deadlines
  inferred from contextual cues ("by this Friday") relative to the meeting date.
- **Kanban dashboard** — auto-generated cards in To Do / In Progress / Done, drag-and-drop
  status changes, filter by owner, sort by deadline, confidence shown per card.
- **Optional audio/video input** — upload a recording; it is transcribed locally with
  OpenAI Whisper before parsing.
- **Evaluation harness** — scores extraction quality against an annotated test set and
  compares prompt variants (see [docs/evaluation-report.md](docs/evaluation-report.md)).

## Architecture

```
Next.js / React frontend  ──HTTP──>  FastAPI backend  ──>  Claude API (structured output)
   Kanban board, filters                REST API              decisions + action items
   transcript / audio upload            SQLAlchemy ORM
                                         Whisper (optional)
                                              │
                                              v
                                     SQLite / PostgreSQL
                                  projects · meetings · tasks · stakeholders
```

See [docs/architecture.md](docs/architecture.md) for detail and [docs/api-spec.md](docs/api-spec.md)
for the full API.

## Tech stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 14, React 18, TypeScript, Tailwind CSS |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 |
| LLM | Claude (Anthropic) via `anthropic` SDK, tool-use structured output |
| Speech-to-text | OpenAI Whisper (optional, local) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Deployment | Docker, Render blueprint |

## Quick start (local)

### Prerequisites
- Python 3.9+ and Node.js 18+
- An Anthropic API key

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then paste your ANTHROPIC_API_KEY into .env
python -m app.seed            # create tables + seed sample project/stakeholders
uvicorn app.main:app --reload --port 8000
```

API docs are served at http://localhost:8000/docs.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open http://localhost:3000.

### 3. (Optional) Audio/video transcription

Whisper is heavy (pulls in PyTorch) and needs the `ffmpeg` binary, so it is opt-in:

```bash
# in backend/, with the venv active
pip install -r requirements-audio.txt
# macOS: brew install ffmpeg   |   Debian/Ubuntu: apt-get install ffmpeg
```

The "Upload audio/video" tab then transcribes the file before parsing. Without it, that
endpoint returns a clear 503 and the text path works as normal.

## Run with Docker

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY
docker compose up --build
```

Frontend on http://localhost:3000, backend on http://localhost:8000. Audio is excluded from
the default image; build with `--build-arg INSTALL_AUDIO=true` to include Whisper.

> Note: the Docker/compose setup is configured but was not built in the development
> environment (no Docker daemon available there); the standalone Next.js build it relies on
> is verified.

## Deploy to Render

1. Push the repo to GitHub.
2. In Render: **New → Blueprint**, point at the repo. It reads [render.yaml](render.yaml) and
   provisions the backend and frontend web services.
3. After the first deploy, set these in the dashboard:
   - backend `ANTHROPIC_API_KEY` (secret) and `CORS_ORIGINS` = the frontend URL.
   - frontend `NEXT_PUBLIC_API_BASE` = `https://<backend>.onrender.com/api/v1`, then redeploy
     the frontend (this value is baked in at build time).

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests/            # API + parser unit tests (LLM mocked)

# from the repo root, eval matcher unit tests:
python -m pytest eval/test_matching.py
```

## Evaluation

```bash
# from the repo root, with the backend venv active and ANTHROPIC_API_KEY set
python -m eval.run_eval --write-report
```

This parses the annotated transcripts in `data/`, scores precision/recall/owner/deadline
accuracy, compares prompt variants, writes `eval/results.json`, and refreshes
[docs/evaluation-report.md](docs/evaluation-report.md).

## Project layout

```
backend/      FastAPI app (api/, llm/, models/, schemas/), tests, Dockerfile
frontend/     Next.js app (src/app, src/components, src/lib), Dockerfile
data/         synthetic-transcripts/ (inputs) + annotated-test-set/ (ground truth)
eval/         evaluation harness + matcher tests
docs/         architecture, API spec, evaluation report
render.yaml   Render deployment blueprint
```

## Scope notes

Out of scope for this iteration (per the project brief): live enterprise integrations
(SAP/Jira/Outlook), real-time multi-user collaboration, and a mobile app. Test data is
synthetic meeting transcripts representing realistic enterprise project scenarios.
