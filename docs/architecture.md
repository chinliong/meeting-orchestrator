# Architecture

## High-level flow

1. The user authenticates via the Next.js frontend — sign in, create an account, or continue as
   a guest. Logged-in users carry a JWT; guests and link recipients carry a board's capability
   token. Either is attached to subsequent requests.
2. The user submits a meeting — pasted transcript text or an uploaded audio/video file.
3. The frontend calls the FastAPI backend (`POST /transcripts` for text, `POST /transcripts/audio`
   for files). Write endpoints require edit access to the target board.
4. For audio, the backend first runs Whisper (a hosted Whisper API by default, or a local model)
   to obtain the transcript text.
5. The backend sends the transcript to Claude with a forced tool-use schema; the response is
   validated into decisions, action items, owners, deadlines, and confidence via Pydantic.
6. The structured data is persisted to the relational database (a `Meeting` plus its `Task` rows).
7. The frontend fetches the task list and renders it two ways — a **Kanban board** (drag-and-drop
   status changes) and a **month calendar** (tasks plotted by deadline, drag-to-reschedule) — both
   with search and owner filtering. Edits are written back with `PATCH /tasks/{id}`; deletes return
   a snapshot so an **Undo** action (button + ⌘Z/Ctrl+Z) can restore via `POST /tasks/restore`.

## Component diagram

```mermaid
flowchart LR
    subgraph Client[Next.js / React frontend]
        A[Auth gate / share-link open]
        U[Transcript / audio upload]
        K[Board + calendar views, filters, search, undo, share]
    end

    subgraph API[FastAPI backend]
        AU[auth router]
        T[transcripts router]
        TK[tasks router]
        P[projects / stakeholders routers]
        AC[access control: owner JWT or workspace token]
        W[Whisper transcription module]
        L[LLM parser module]
    end

    DB[(SQLite / PostgreSQL)]
    C[Claude API]

    A -->|POST /auth/signup, /auth/login| AU
    U -->|POST /transcripts and /transcripts/audio| T
    K -->|GET /tasks, PATCH /tasks/id| TK
    K -->|GET /projects, GET /projects/by-token| P
    AU --> DB
    T --> AC
    TK --> AC
    P --> AC
    AC --> DB
    T -->|audio bytes| W
    W -->|transcript text| T
    T -->|transcript text| L
    L -->|tool-use request| C
    C -->|structured JSON| L
    T -->|persist meeting + tasks| DB
```

## Components

- **Frontend (Next.js/React):** auth gate (sign in / create account / continue as guest), a
  **Kanban board** and a **month calendar** view (toggle), owner filter / deadline sort / text
  search, an **undo** stack (button + ⌘Z/Ctrl+Z) over status/edit/reschedule/delete actions,
  transcript-and-audio upload, and a share dialog exposing view/edit links. A small session layer
  persists the account token and guest boards in `localStorage`. Talks to the backend via
  `src/lib/api.ts`, which attaches the `Authorization` bearer and `X-Workspace-Token` headers.
- **Backend (FastAPI):**
  - `POST /auth/signup` (with optional guest-board claim), `POST /auth/login`, `GET /auth/me`,
    `POST /auth/password` (change password), `DELETE /auth/me` (delete account; owned boards are
    orphaned to guest boards), and `POST /auth/forgot-password` + `POST /auth/reset-password`
    (emailed 6-digit reset code).
  - `GET|POST /projects`, `GET /projects/by-token/{token}` (open a share link),
    `PATCH|DELETE /projects/{id}`.
  - `POST /transcripts`, `POST /transcripts/audio`, `GET /transcripts/{id}`,
    `PATCH /transcripts/{id}` (rename a meeting; reflected on its tasks).
  - `GET|POST /tasks`, `PATCH /tasks/{id}`, `DELETE /tasks/{id}` (returns a snapshot for undo),
    `POST /tasks/restore` (recreate a deleted task with its original id). `GET /tasks` filters by
    `project_id`, `owner`, `status`, `due_before`, `due_after`; with no `project_id` an
    authenticated user gets tasks across all boards they own.
  - `GET|POST /stakeholders`.
  - `PATCH /auth/notifications` (set deadline-reminder preferences), `POST /auth/notifications/test`
    (send a one-off preview digest).
  - **Auth & access control** (`app/auth.py`) — bcrypt password hashing, JWT issue/verify, and
    `project_access_level()` which resolves a request to `edit` / `view` / no-access from the
    bearer user (owner) or the `X-Workspace-Token` (edit/view token).
  - **Email sender** (`app/email.py`) — sends password-reset codes and deadline reminders. Prefers
    Brevo's HTTPS API (`BREVO_API_KEY`) so it works on hosts that block outbound SMTP (e.g. Render's
    free tier), falls back to SMTP, and otherwise logs the message. Reset emails are dispatched via
    FastAPI background tasks so a slow send never holds the request open.
  - **Deadline reminders** (`app/notifications.py`) — opt-in (off by default) per account, with a
    per-project mute and a configurable "days before" threshold. `python -m app.notify_due_tasks`
    runs the daily check; intended to be triggered by an external scheduler (e.g. a Render Cron
    Job), since the web service itself only runs it on demand via the test-send endpoint. See
    "Deadline reminders" below.
  - **LLM parser** (`app/llm/parser.py`) — a reusable, framework-agnostic module: raw text in,
    validated `ExtractionResult` out, via Claude tool-use.
  - **Whisper module** (`app/llm/transcription.py`) — optional, lazily imported; prefers a hosted
    Whisper API and falls back to a local model, so the core app runs without the heavy dependency.
- **Database:** PostgreSQL (prod) / SQLite (dev), via SQLAlchemy. Tables: `users`, `projects`,
  `meetings`, `stakeholders`, `tasks`, `password_resets`.
- **LLM provider:** Claude (Anthropic), structured output through a forced `record_extraction` tool.

## Access model

- A project is owned by a user (`owner_user_id`) or unowned (guest-created).
- Each project has two permanent capability tokens: `view_token` (read-only) and `edit_token`
  (read/write). A request gains access by being the owner (JWT) **or** presenting a matching token.
- `ProjectOut` returns the `edit_token` only to edit-level callers, so a view link never leaks
  write access. On sign-up, a guest's `edit_token`s can be supplied to claim those boards.
- Sharing is asynchronous (no live sync); concurrent edits are last-write-wins.

## Deadline reminders

- Opt-in per account (`User.notify_email`, default off) with a configurable
  `notify_days_before`, plus a per-project mute (`Project.notify_muted`) that overrides the
  account setting for one board.
- `app/notifications.py` finds tasks inside their reminder window — from `notify_days_before`
  days out through one day past the deadline (a one-time overdue nudge, not a repeat) — and
  emails each affected account holder a single digest covering every newly-due task across their
  (unmuted) projects.
- Idempotency: `Task.last_notified_for` records the deadline last notified for, so re-running the
  same day, or after the deadline, never double-sends. Rescheduling a task's deadline clears the
  match, re-opening the window.
- `python -m app.notify_due_tasks` runs one pass; nothing inside the web service calls it on a
  schedule, so it needs an external trigger (e.g. a Render Cron Job once a day) to run in
  production. `POST /auth/notifications/test` runs the same logic on demand for one user, useful
  for confirming the email channel works without waiting for the daily job.

## Data model

```mermaid
erDiagram
    USER ||--o{ PROJECT : owns
    USER ||--o{ PASSWORD_RESET : requests
    PROJECT ||--o{ MEETING : has
    PROJECT ||--o{ TASK : has
    MEETING ||--o{ TASK : produces
    USER {
        int id PK
        string email
        string password_hash
        bool notify_email
        int notify_days_before
    }
    PASSWORD_RESET {
        int id PK
        int user_id FK
        string code_hash
        datetime expires_at
        int attempts
        bool used
    }
    PROJECT {
        int id PK
        int owner_user_id FK
        string name
        text description
        string view_token
        string edit_token
        bool notify_muted
    }
    MEETING {
        int id PK
        int project_id FK
        string title
        text transcript_text
        enum status
        text error_message
    }
    TASK {
        int id PK
        int project_id FK
        int meeting_id FK
        text description
        string owner
        date deadline
        enum status
        float confidence
        text source_decision
        date last_notified_for
    }
    STAKEHOLDER {
        int id PK
        string name
        string email
    }
```

A task exposes its source meeting's title (`meeting_title`) for display; manually-added tasks have
no `meeting_id` and carry full confidence.

## Reliability notes

- LLM/API failures during parsing are caught and recorded on the meeting (`status = failed`,
  `error_message`) rather than crashing the request, so the client always gets a response.
- The audio endpoint degrades gracefully: if no Whisper backend is configured it returns `503`
  with an actionable message instead of failing at import time.
- The schema is created on startup via `create_all`, which never alters existing tables; after a
  schema change, `python -m app.reset_db` rebuilds and re-seeds the database.
