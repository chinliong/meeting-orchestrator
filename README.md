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
- **Two views — Kanban & calendar** — a Kanban board (auto-generated cards in To Do / In Progress
  / Done with drag-and-drop status changes) and a month calendar that plots tasks by their deadline
  with drag-to-reschedule (drag onto a "no deadline" tray to clear it). Both support owner filtering
  and a search across task text, owners, and source meetings; cards show extraction confidence.
- **Undo** — an Undo button (and ⌘Z / Ctrl+Z) reverses status changes, edits, reschedules, and
  deletes; a deleted task is restored with its original id.
- **Manual & sourced tasks** — tasks are usually extracted from a meeting (the source meeting
  title shows on each card and can be renamed inline), but you can also add tasks by hand for
  work raised outside a captured meeting.
- **Accounts & guest mode** — sign up to keep your boards under an account, or continue as a
  guest (guest boards are kept on the device and can be carried into an account on sign-up).
- **Account self-service** — change your password, reset a forgotten one with a 6-digit code
  emailed to you, or delete your account (owned boards are released as guest boards rather than
  destroyed, so existing share links keep working).
- **Deadline email reminders** — opt-in (off by default) digest emails for tasks about to be due
  or just gone overdue, with a configurable "remind me N days before" and a per-project mute.
- **Shareable boards** — every board has a permanent **view link** and **edit link**; anyone
  with a link can open it (no account needed). View links are read-only; the UI hides every
  editing affordance on a view-only board.
- **Optional audio/video input** — upload a recording; it is transcribed with Whisper (a hosted
  Whisper API by default, or a local model) before parsing.
- **Evaluation harness** — scores extraction quality against an annotated test set and
  compares prompt variants (see [docs/evaluation-report.md](docs/evaluation-report.md)).

## Architecture

```
Next.js / React frontend  ──HTTP──>  FastAPI backend  ──>  Claude API (structured output)
   Kanban + calendar views,           REST API,             decisions + action items
   filters, search, undo, share       JWT auth + share
   transcript / audio upload          tokens, SQLAlchemy
                                       Whisper (optional)
                                              │
                                              v
                                     SQLite (dev) / PostgreSQL (prod)
              users · projects · meetings · tasks · stakeholders · password_resets
```

See [docs/architecture.md](docs/architecture.md) for detail and [docs/api-spec.md](docs/api-spec.md)
for the full API.

## Tech stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 14, React 18, TypeScript, Tailwind CSS |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 |
| Auth | Email/password (bcrypt via passlib), JWT access tokens, capability-link sharing |
| Email | Brevo transactional API (HTTPS) for password resets and deadline reminders; SMTP fallback for local dev |
| LLM | Claude (Anthropic) via `anthropic` SDK, tool-use structured output |
| Speech-to-text | Whisper — hosted API (OpenAI/Groq) by default, optional local model |
| Database | SQLite (dev) / PostgreSQL (prod; e.g. Neon) |
| Deployment | Docker, Render blueprint (frontend + backend) + external Postgres |

## Access model (accounts, guests, sharing)

- **Accounts** identify an owner. `GET /projects` returns the signed-in user's own boards.
- **Capability links** are the sharing mechanism: each project carries a permanent `view_token`
  and `edit_token`. The frontend sends a board's token in an `X-Workspace-Token` header; an edit
  token grants read/write, a view token grants read-only.
- **Guests** have no account — they reach boards purely by capability link, and their boards are
  remembered in the browser. On sign-up, guest boards are claimed into the new account.
- Links are **permanent and not revocable** by design (documented in the share dialog); treat
  them like passwords.

## Quick start (local)

### Prerequisites
- Python 3.9+ and Node.js 18+
- An Anthropic API key

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # paste your ANTHROPIC_API_KEY; set AUTH_SECRET for production
python -m app.seed            # create tables + seed sample data and a demo account
uvicorn app.main:app --reload --port 8000
```

`python -m app.seed` prints a demo login (`demo@example.com` / `demo1234`) that owns the sample
boards. API docs are served at http://localhost:8000/docs.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open http://localhost:3000. You'll land on the **Sign in / Create account / Continue as guest**
screen.

### 3. (Optional) Audio/video transcription

Audio is transcribed by a hosted Whisper API by default — set `TRANSCRIPTION_API_KEY` (OpenAI, or
Groq with `TRANSCRIPTION_BASE_URL`/`TRANSCRIPTION_MODEL`) in `.env`. This works on memory-limited
hosts. Alternatively, run Whisper locally (heavier — pulls in PyTorch and needs `ffmpeg`):

```bash
# in backend/, with the venv active
pip install -r requirements-audio.txt
# macOS: brew install ffmpeg   |   Debian/Ubuntu: apt-get install ffmpeg
```

With neither configured, the audio endpoint returns a clear `503` and the text path works as normal.

### 4. (Optional) Email delivery

Password-reset codes and deadline reminders both go through `app/email.py`. **If no provider is
configured, the message is logged instead** — enough for local testing. To send for real:

- **Brevo HTTPS API** (recommended; required on hosts that block SMTP, like Render's free tier):
  create a free [Brevo](https://www.brevo.com) account, verify a sender, generate an API key, then
  set `BREVO_API_KEY` and `SMTP_FROM` (the verified sender).
- **SMTP**: set `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM` — e.g. Gmail with
  an App Password.

Deadline reminders are opt-in per account (off by default — toggle in Account settings) and only
send when a daily check runs: locally, run `python -m app.notify_due_tasks` (or schedule it via
cron); on Render, see step 5 of the deploy steps below. Use the "Send test email" button in Account
settings to verify delivery. See `backend/.env.example` for all email vars and
[docs/architecture.md](docs/architecture.md#deadline-reminders) for how reminders work.

## Run with Docker

```bash
cp .env.example .env          # set ANTHROPIC_API_KEY (and AUTH_SECRET)
docker compose up --build
```

Frontend on http://localhost:3000, backend on http://localhost:8000. Audio is excluded from
the default image; build with `--build-arg INSTALL_AUDIO=true` to include local Whisper.

## Deploy to Render + external Postgres

The blueprint provisions a backend web service and a frontend web service on the free tier. The
database is an **external Postgres** (e.g. a free [Neon](https://neon.tech) project) referenced by
`DATABASE_URL`, so it isn't subject to a managed-DB expiry window.

1. Push the repo to GitHub.
2. In Render: **New → Blueprint**, point at the repo. It reads [render.yaml](render.yaml).
3. Fill in the `sync: false` env vars (Render names services predictably as
   `https://<name>.onrender.com`):
   - backend `ANTHROPIC_API_KEY` = your key
   - backend `DATABASE_URL` = your Postgres connection string
     (`postgresql://…/<db>?sslmode=require`; `db.py` normalises `postgres://` URLs)
   - backend `CORS_ORIGINS` = `https://orchestrator-frontend.onrender.com`
   - frontend `NEXT_PUBLIC_API_BASE` = `https://orchestrator-backend.onrender.com/api/v1`
   - backend `BREVO_API_KEY` + `SMTP_FROM` (optional) = enable password-reset and deadline-reminder
     emails — see "Email delivery" above. **Render's free tier blocks outbound SMTP**, so the
     Brevo HTTPS API is required there; the `SMTP_*` host/port/user/password vars won't work.

   `AUTH_SECRET` and `CRON_SECRET` are generated automatically by the blueprint. `NEXT_PUBLIC_API_BASE`
   is baked in at build time, so changing it requires a frontend redeploy.
4. Apply. The schema is created automatically on first startup against an empty database.
5. (Optional) To enable automatic deadline reminders, copy the generated `CRON_SECRET` from the
   backend service's Environment tab, then set up a free scheduler like
   [cron-job.org](https://cron-job.org) to hit
   `https://<your-backend>.onrender.com/api/v1/internal/notify-due-tasks?secret=<CRON_SECRET>`
   once a day.

Seeding sample data: Render's web shell is a paid feature, so run the seed from your own machine
pointed at the deployed database:

```bash
cd backend
DATABASE_URL="<your Postgres connection string>" python -m app.seed
```

If you change the schema later, the startup `create_all` does **not** alter existing tables — run
`python -m app.reset_db` (drops, recreates, and re-seeds — **destructive**) against that
`DATABASE_URL` to rebuild it.

Note on the free tier: web services spin down after ~15 min idle and cold-start in ~50s.

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
backend/      FastAPI app (api/, llm/, models/, schemas/, auth.py, email.py, notifications.py), tests, Dockerfile
frontend/     Next.js app (src/app, src/components, src/lib), Dockerfile
data/         synthetic-transcripts/ (inputs) + annotated-test-set/ (ground truth)
eval/         evaluation harness + matcher tests
docs/         architecture, API spec, evaluation report
render.yaml   Render deployment blueprint
```

## Scope notes

Per the project brief, **real-time** multi-user collaboration (live presence / simultaneous
co-editing) is out of scope, as are live enterprise integrations (SAP/Jira/Outlook) and a mobile
app. The accounts and capability-link sharing added here are **asynchronous** — others see changes
on reload, with last-write-wins and no live conflict resolution. Test data is synthetic meeting
transcripts representing realistic enterprise project scenarios.
