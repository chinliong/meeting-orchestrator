# Architecture

## High-level flow

1. The user authenticates via the Next.js frontend: sign in, create an account, or continue as
   a guest. Logged-in users carry a JWT; guests and link recipients carry a board's capability
   token. Either is attached to subsequent requests.
2. The user submits a meeting: pasted transcript text or an uploaded audio/video file.
3. The frontend calls the FastAPI backend (`POST /transcripts` for text, `POST /transcripts/audio`
   for files). Write endpoints require edit access to the target board.
4. For audio, the backend first transcribes the file with a hosted service (Deepgram Nova-3) to
   obtain the transcript text.
5. The backend sends the transcript to Gemini with a forced function-call schema; the response
   is validated into decisions, action items, owners, deadlines, and confidence via Pydantic.
6. The structured data is persisted to the relational database (a `Meeting` plus its `Task` rows).
7. The frontend fetches the task list and renders it two ways: a **Kanban board** (drag-and-drop
   status changes) and a **month calendar** (tasks plotted by deadline, drag-to-reschedule), both
   with search and owner filtering. Edits are written back with `PATCH /tasks/{id}`; deletes return
   a snapshot so an **Undo** action (button + ⌘Z/Ctrl+Z) can restore via `POST /tasks/restore`.

## Component diagram

The request path. Every router resolves access through one dependency before touching the
database; the routers themselves are listed in full under **Components** below.

```mermaid
flowchart LR
    subgraph Client[Next.js / React frontend]
        direction TB
        A[Auth gate and share links]
        U[Transcript / audio upload]
        K[Board, calendar, filters,<br/>search, undo]
    end

    subgraph API[FastAPI backend]
        direction TB
        R[API routers<br/>auth, projects, transcripts, tasks,<br/>subtasks, attachments, stakeholders]
        AC[Access control<br/>owner JWT or workspace token]
        L[LLM module<br/>parser + subtask generator]
        W[Transcription module]
    end

    DB[(SQLite / PostgreSQL)]
    G[Gemini API]
    D[Deepgram API]

    A -->|JWT or workspace token| R
    U -->|transcript text or audio| R
    K -->|board reads and writes| R
    R --> AC
    AC -->|edit / view / none| DB
    R -->|audio bytes| W
    W -->|transcript text| R
    W --> D
    R -->|transcript + meeting date| L
    L -->|forced tool use| G
    G -->|structured JSON| L
    L -->|validated result| R
```

The daily reminder pass runs on its own path, triggered from outside rather than by a user.

```mermaid
flowchart LR
    X[External scheduler<br/>once a day] -->|shared secret| I[internal router]
    I --> N[Reminder module]
    DB[(Database)] -->|tasks entering their window| N
    N -->|one digest per user| M[Email module]
    AU[auth router] -->|password reset code| M
    M -->|Brevo HTTPS, SMTP, or log| OUT[Recipient]
```

## Components

- **Frontend (Next.js/React):** auth gate (sign in / create account / continue as guest), a
  **Kanban board** and a **month calendar** view (toggle), owner filter / deadline sort / text
  search, an **undo** stack (button + ⌘Z/Ctrl+Z) over status/edit/reschedule/delete actions,
  transcript-and-audio upload, and a share dialog exposing view/edit links. A small session layer
  persists the account token and guest boards in `localStorage`. Talks to the backend via
  `src/lib/api.ts`, which attaches the `Authorization` bearer and `X-Workspace-Token` headers.
- **Backend (FastAPI):** every route below is mounted under `/api/v1` (so `POST /auth/signup` is
  served at `/api/v1/auth/signup`). The complete surface, with request and response shapes, is in
  [api-spec.md](api-spec.md).
  - `POST /auth/signup` (with optional guest-board claim), `POST /auth/login`, `GET /auth/me`,
    `POST /auth/password` (change password), `DELETE /auth/me` (delete account; owned boards are
    orphaned to guest boards), and `POST /auth/forgot-password` + `POST /auth/reset-password`
    (emailed 6-digit reset code).
  - `GET|POST /projects`, `GET /projects/{id}`, `GET /projects/by-token/{token}` (open a share
    link), `PATCH|DELETE /projects/{id}`, `POST /projects/{id}/rotate-token` (owner-only; replaces
    the view or edit token, invalidating every copy of the old one while the other keeps working).
  - `POST /transcripts`, `POST /transcripts/audio`, `GET /transcripts/{id}`,
    `PATCH /transcripts/{id}` (rename a meeting; reflected on its tasks).
  - `GET|POST /tasks`, `PATCH /tasks/{id}`, `DELETE /tasks/{id}` (returns a snapshot for undo),
    `POST /tasks/restore` (recreate a deleted task with its original id). `GET /tasks` filters by
    `project_id`, `owner`, `status`, `due_before`, `due_after`; with no `project_id` an
    authenticated user gets tasks across all boards they own.
  - `GET|POST /tasks/{id}/subtasks`, `POST /tasks/{id}/subtasks/generate` (LLM breakdown from the
    task's own details or from typed instructions), `PATCH|DELETE /subtasks/{id}`.
  - `GET|POST /tasks/{id}/attachments`, `GET|DELETE /attachments/{id}`. Bytes are streamed back
    behind the same credential headers as every other call, so an attachment is not reachable
    through a bare unauthenticated link.
  - `GET|POST /stakeholders`.
  - `PATCH /auth/notifications` (set deadline-reminder preferences), `POST /auth/notifications/test`
    (send a one-off preview digest).
  - `GET /health`: liveness, plus the extraction model the deployment will actually use and
    whether transcription is configured. Names the model, never a key.
  - **Auth & access control** (`app/auth.py`): bcrypt password hashing, JWT issue/verify, and
    `project_access_level()` which resolves a request to `edit` / `view` / no-access from the
    bearer user (owner) or the `X-Workspace-Token` (edit/view token).
  - **Email sender** (`app/email.py`): sends password-reset codes and deadline reminders. Prefers
    Brevo's HTTPS API (`BREVO_API_KEY`) so it works on hosts that block outbound SMTP (e.g. Render's
    free tier), falls back to SMTP, and otherwise logs the message. Reset emails are dispatched via
    FastAPI background tasks so a slow send never holds the request open.
  - **Deadline reminders** (`app/notifications.py`): opt-in (off by default) per account, with
    per-project opt-in selection and a configurable "days before" threshold. `GET /internal/notify-due-tasks`
    (shared-secret protected) runs the daily check over HTTP, for a free external scheduler to
    call once a day. See "Deadline reminders" below.
  - **LLM parser** (`app/llm/parser.py`): a reusable, framework-agnostic module: raw text in,
    validated `ExtractionResult` out, via a forced function call. Relative deadline cues ("by Friday")
    resolve against the meeting's `meeting_date`, falling back to its upload date; the anchor is
    never inferred from the transcript body, where a freeze or go-live date would be mistaken
    for it.
  - **Subtask generator** (`app/llm/subtasks.py`): breaks a single task into an ordered checklist,
    either from the task's own details or from user-supplied instructions. Provider is selected
    separately from the parser's (`SUBTASK_PROVIDER`), because open-ended decomposition is a
    different problem from extraction and was measured on its own rubric.
  - **Gemini client** (`app/llm/gemini.py`): the forced function call plus the JSON-Schema to
    OpenAPI translation both LLM modules share, so the tool schema is defined once.
  - **Transcription module** (`app/llm/transcription.py`): optional, lazily imported, resolved by
    configuration in three tiers: Deepgram Nova-3 first, then any OpenAI-compatible endpoint via
    `TRANSCRIPTION_BASE_URL` (Groq, OpenAI), then an optional local Whisper install. The first two
    are hosted, so nothing loads into memory and the core app runs without the heavy local
    dependency; with none configured the audio endpoint returns a clear unavailable status rather
    than failing at import. Model choice is measured in [asr-evaluation.md](asr-evaluation.md).
- **Database:** PostgreSQL (prod) / SQLite (dev), via SQLAlchemy. Tables: `users`, `projects`,
  `meetings`, `stakeholders`, `tasks`, `subtasks`, `attachments`, `password_resets`. Attachment
  bytes are stored in the `attachments` row (the deploy target has an ephemeral filesystem and no
  object storage), size-capped in the API. The engine is created with `pool_pre_ping` (and a 5-min
  `pool_recycle`) because serverless Postgres (Neon) drops idle connections; without it, the first
  request after the free backend wakes from sleep fails with "SSL connection has been closed
  unexpectedly"; pre-ping validates and reconnects transparently instead.
- **LLM provider:** Gemini Flash for both extraction and subtask generation, structured output
  through a forced function call. The tool schema is defined once and translated into Gemini's
  OpenAPI subset (`app/llm/gemini.py`); the translation raises on anything it does not recognise
  rather than dropping it silently, so a schema change cannot weaken the contract unnoticed.
- **Why Gemini:** on extraction it is never significantly behind Claude Sonnet on F1 on either
  the short development set or the long held-out set, it is more precise on both, and it costs a
  tenth of Sonnet's input price (`docs/evaluation-report.md`). Subtask quality is indistinguishable between the two on both
  sets (p = 0.652 and p = 1.0), so there the reason is cost and keeping one provider.

## Access model

- A project is owned by a user (`owner_user_id`) or unowned (guest-created).
- Each project has two permanent capability tokens: `view_token` (read-only) and `edit_token`
  (read/write). A request gains access by being the owner (JWT) **or** presenting a matching token.
- `ProjectOut` returns the `edit_token` only to edit-level callers, so a view link never leaks
  write access. On sign-up, a guest's `edit_token`s can be supplied to claim those boards.
- Sharing is asynchronous (no live sync); concurrent edits are last-write-wins.

## Deadline reminders

- Opt-in per account (`User.notify_email`, default off) with a configurable
  `notify_days_before`, plus per-project opt-in (`Project.notify_enabled`, default off): a board
  is reminded only when both the account flag and that board's flag are on. The user picks which
  boards remind them from the project checklist in Account settings.
- `app/notifications.py` finds tasks inside their reminder window, from `notify_days_before`
  days out through one day past the deadline (a one-time overdue nudge, not a repeat), and
  emails each affected account holder a single digest covering every newly-due task across their
  reminder-enabled projects.
- Idempotency: `Task.last_notified_for` records the deadline last notified for, so re-running the
  same day, or after the deadline, never double-sends. Rescheduling a task's deadline clears the
  match, re-opening the window.
- The window is date-based, so "today" is computed in `REMINDER_TIMEZONE` (IANA zone, default UTC).
  The server clock is UTC, which would otherwise put a reminder a day off for users elsewhere: a
  task due "Jun 24" with a one-day lead enters its window at 08:00 SGT on Jun 23 under plain UTC.
- Two ways to trigger a pass: `python -m app.notify_due_tasks` (a CLI script, useful for a local
  cron entry or manual runs) and `GET /internal/notify-due-tasks` (the same logic over HTTP,
  guarded by a shared secret `CRON_SECRET` instead of a user session). The latter is meant for a
  free external scheduler (e.g. cron-job.org) hitting it once a day: Render has no built-in free
  scheduler and Render Cron Jobs are a paid add-on, so this avoids that cost entirely.
- `POST /auth/notifications/test` runs the same logic on demand for one signed-in user, useful for
  confirming the email channel works without waiting for the daily trigger.

## Data model

```mermaid
erDiagram
    USER ||--o{ PROJECT : owns
    USER ||--o{ PASSWORD_RESET : requests
    PROJECT ||--o{ MEETING : has
    PROJECT ||--o{ TASK : has
    MEETING ||--o{ TASK : produces
    TASK ||--o{ SUBTASK : "broken into"
    TASK ||--o{ ATTACHMENT : has
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
        bool notify_enabled
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
    SUBTASK {
        int id PK
        int task_id FK
        string title
        bool done
        int position
    }
    ATTACHMENT {
        int id PK
        int task_id FK
        string filename
        string content_type
        int size
        blob data
    }
    STAKEHOLDER {
        int id PK
        string name
        string email
    }
```

A task exposes its source meeting's title and date (`meeting_title`, `meeting_date`) for display,
so meetings in a series that share a title stay distinguishable on the board; manually-added tasks
have no `meeting_id` and carry full confidence. `stakeholders` deliberately has no foreign key to
`tasks`: a task's `owner` is a plain name string, matched against `stakeholders.name` only for the
owner filter, because the people who own action items in a meeting are usually not users of the
tool and requiring each of them to hold an account would make the extraction unusable.

## Reliability notes

- LLM/API failures during parsing are caught and recorded on the meeting (`status = failed`,
  `error_message`) rather than crashing the request, so the client always gets a response.
- The audio endpoint degrades gracefully: if no transcription backend is configured it returns `503`
  with an actionable message instead of failing at import time.
- The schema is created on startup via `create_all`, which adds missing tables but never alters
  existing ones. New tables (e.g. `subtasks`, `attachments`) appear automatically; a new column on
  an existing table needs an additive migration (`app/migrate_add_meeting_date.py`,
  `app/migrate_add_notifications.py`, `app/migrate_reminder_optin.py`). `python -m app.reset_db` rebuilds and re-seeds from scratch.
