# API Specification

Base URL: `/api/v1`. Interactive docs (Swagger UI) are served at `/docs` when the backend runs.

All request/response bodies are JSON unless noted. Dates are ISO 8601 (`YYYY-MM-DD`).

## Authentication & access

Two credentials are accepted, together or alone:

- `Authorization: Bearer <jwt>` — identifies a signed-in user, who owns the boards they create.
- `X-Workspace-Token: <token>` — a board's capability token from a share link. An **edit** token
  grants read/write; a **view** token grants read-only.

For a given board, access resolves to `edit`, `view`, or none. Reads require `view`; writes
require `edit`. Missing access returns `403`; a missing board returns `404`; routes that require a
signed-in user return `401`.

## Health

### `GET /health`
Returns `{ "status": "ok" }`.

## Auth

### `POST /auth/signup`
Body `{ "email": "string", "password": "string", "claim_tokens": ["edit_token", ...] }`.
`claim_tokens` is optional — edit tokens of guest boards to adopt into the new account.
Returns `201` `{ "token": "<jwt>", "user": { "id", "email", "created_at", "notify_email", "notify_days_before" } }`.
`409` if the email already exists.

### `POST /auth/login`
Body `{ "email": "string", "password": "string" }` → `200` `{ "token", "user" }`; `401` on bad
credentials.

### `GET /auth/me`
Returns the current user (requires bearer). `401` if unauthenticated.

### `POST /auth/password`
Change the signed-in user's password. Requires bearer. Body
`{ "current_password": "string", "new_password": "string" }`. `204` on success; `401` if the
current password is wrong; `400` if the new password is empty.

### `PATCH /auth/notifications`
Update the signed-in user's deadline-reminder preferences. Requires bearer. Body
`{ "notify_email": bool, "notify_days_before": int }` (0–14). Returns the updated user object.
Off (`notify_email: false`) by default for every new account.

### `POST /auth/notifications/test`
Send a one-off preview digest to the signed-in user's own email — whatever tasks would currently
trigger a reminder, or a "nothing due" confirmation if none do. Requires bearer and
`notify_email` already enabled (`400` otherwise).

### `DELETE /auth/me`
Delete the signed-in user's account. Requires bearer. The user's owned boards are **orphaned**
(`owner_user_id` set to null) rather than deleted, so they revert to guest boards still reachable
by their share links. `204`.

### `POST /auth/forgot-password`
Request a password-reset code. Body `{ "email": "string" }`. Always returns `204` — whether or not
the email matches an account — so the endpoint can't be used to probe which addresses are
registered. If the email exists, a single-use 6-digit code (valid 15 minutes) is generated and
emailed in the background; any earlier outstanding codes for that user are invalidated.

### `POST /auth/reset-password`
Complete a reset. Body `{ "email": "string", "code": "string", "new_password": "string" }`.
`204` on success. `400` (`Invalid or expired code`) if the code is wrong, expired, already used,
or the new password is empty. The code is invalidated after success or after too many wrong
attempts.

## Projects

A project object:
```json
{
  "id": 1, "name": "string", "description": "string",
  "created_at": "2026-06-17T09:30:00",
  "owner_user_id": 1,
  "notify_enabled": false,
  "access_level": "edit",
  "view_token": "string",
  "edit_token": "string | null"
}
```
`edit_token` is returned only to edit-level callers. `notify_enabled` opts this project **in** to
deadline reminders (off by default); reminders are sent only when this is on **and** the owner has
reminders enabled account-wide.

### `GET /projects`
Lists the signed-in user's own boards (newest first). Requires bearer (`401` otherwise). Guests
reach their boards by share link.

### `POST /projects`
Body `{ "name": "string", "description": "string (optional)" }` → `201` project object. Owned by
the signed-in user, or unowned (guest) if anonymous.

### `GET /projects/by-token/{token}`
Resolves a share link to its board at the level the token grants (`edit` or `view`). `404` if the
token matches nothing.

### `PATCH /projects/{project_id}`
Update `name` / `description` / `notify_enabled`. Requires edit access. Returns the project;
`404`/`403` as above.

### `DELETE /projects/{project_id}`
Removes the project and cascades to its meetings and tasks. Requires edit access. `204`.

## Transcripts

### `POST /transcripts`
Submit raw transcript text for parsing. Requires edit access to `project_id`. Synchronously runs
the LLM and stores the extracted tasks. A blank `title` is given a dated default.

Request:
```json
{
  "project_id": 1,
  "title": "SAP FI/CO Finance Workshop #4",
  "transcript_text": "Aisha: Daniel, where are we with the cost center hierarchy migration? ..."
}
```

Response `201 Created` — a meeting object with its extracted tasks:
```json
{
  "id": 12,
  "project_id": 1,
  "title": "SAP FI/CO Finance Workshop #4",
  "status": "complete",
  "error_message": null,
  "created_at": "2026-06-17T09:30:00",
  "tasks": [
    {
      "id": 40, "project_id": 1, "meeting_id": 12,
      "meeting_title": "SAP FI/CO Finance Workshop #4",
      "description": "Finish the APAC cost center hierarchy mapping",
      "owner": "Daniel", "deadline": "2026-06-19", "status": "todo",
      "confidence": 0.95, "source_decision": null,
      "created_at": "2026-06-17T09:30:01"
    }
  ]
}
```
On LLM/API failure the meeting is returned with `status: "failed"` and an `error_message`
(still `201`), and no tasks.

### `POST /transcripts/audio`
Submit an audio/video file (`multipart/form-data`). Transcribed with Whisper, then parsed.
Requires edit access to `project_id`.

Form fields: `project_id` (int), `title` (string, optional), `file` (the upload).

Responses: `201` (same shape as above) · `400` empty file · `403` no edit access ·
`404` unknown project · `503` if no Whisper backend is configured.

### `GET /transcripts/{meeting_id}`
Returns the meeting's status and its extracted tasks. Requires view access. `404` if not found.

### `PATCH /transcripts/{meeting_id}`
Rename a meeting. Body `{ "title": "string" }`. The new title is reflected on every task from that
meeting. Requires edit access. `404` if not found.

## Tasks

A task object includes `meeting_title` (the source meeting's title, `null` for manually-added
tasks) and three read-only rollup counts: `subtask_total`, `subtask_done`, and `attachment_count`.

### `GET /tasks`
Query params (all optional): `project_id`, `owner`, `status` (`todo|in_progress|done`),
`due_before`, `due_after`. With `project_id`, requires view access to that board. With no
`project_id`, requires a signed-in user and returns tasks across all boards they own (`401`
otherwise).

### `POST /tasks`
Add a task by hand. Body `{ "project_id", "description", "owner?", "deadline?", "status?" }` →
`201` task object. Requires edit access. Manually-added tasks have no `meeting_id` and
`confidence` defaults to `1.0`.

### `PATCH /tasks/{task_id}`
Update any of `description`, `owner`, `deadline`, `status`. Requires edit access to the task's
board. Returns the updated task; `404` if not found.

### `DELETE /tasks/{task_id}`
Removes the task. Requires edit access. `404` if not found. Returns `200` with a snapshot of what
was removed, so the client can offer an **undo**:
```json
{ "task": { "id": 40, "project_id": 1, "...": "full task object" } }
```

### `POST /tasks/restore`
Recreates a previously deleted task from a `DELETE` snapshot — powers undo. Body is the snapshot
above (`{ "task": { ... } }`). The task is restored with its **original id** (so references stay
valid). Requires edit access to the task's board. `201` with the restored task; `409` if a task
with that id already exists. A dangling `meeting_id` (its meeting was deleted meanwhile) is cleared.

## Subtasks

A subtask is a checklist item under a task: `{ "id", "task_id", "title", "done", "position" }`.
All routes require **view** access to read and **edit** access to mutate; subtasks cascade-delete
with their task.

### `GET /tasks/{task_id}/subtasks`
List a task's subtasks in order. Requires view access.

### `POST /tasks/{task_id}/subtasks`
Body `{ "title": "string" }` → `201` subtask (appended at the end). `422` if the title is blank.
Requires edit access.

### `POST /tasks/{task_id}/subtasks/generate`
Have the LLM break the task down and append the suggestions as real subtasks. Body
`{ "instructions": "string | null" }` — when `instructions` is non-empty the model is steered by
that text ("from your instructions"), otherwise it works from the task's own details ("from task
details"). Returns `201` with the newly-created subtasks. `502` if the model call fails or returns
nothing. Requires edit access.

### `PATCH /subtasks/{subtask_id}`
Update `title` and/or `done`. `422` on a blank title. Requires edit access. `404` if not found.

### `DELETE /subtasks/{subtask_id}`
Removes the subtask. Requires edit access. `204`. `404` if not found.

## Attachments

A file attached to a task. Metadata object: `{ "id", "task_id", "filename", "content_type",
"size", "created_at" }` — the bytes themselves are stored in the database and streamed only by the
download route. Attachments cascade-delete with their task.

### `GET /tasks/{task_id}/attachments`
List a task's attachment metadata. Requires view access.

### `POST /tasks/{task_id}/attachments`
Upload a file (`multipart/form-data`, field `file`) → `201` attachment metadata. Requires edit
access. `400` empty file · `413` over the 10 MB limit.

### `GET /attachments/{attachment_id}`
Download the file bytes (with a `Content-Disposition` filename). Requires view access. `404` if not
found. The client fetches this with the auth/workspace headers, so it isn't a plain link.

### `DELETE /attachments/{attachment_id}`
Removes the attachment. Requires edit access. `204`. `404` if not found.

## Stakeholders

### `GET /stakeholders`
List stakeholders (alphabetical).

### `POST /stakeholders`
Body `{ "name": "string", "email": "string (optional)" }` → `201` stakeholder object.

## Internal

### `GET /internal/notify-due-tasks`
Runs one deadline-reminder pass (see [architecture.md](architecture.md#deadline-reminders)).
Meant to be called once a day by an external scheduler rather than a logged-in client — there's
no bearer/workspace token, so it's protected by a shared secret (`CRON_SECRET`) instead, passed
as either an `X-Cron-Secret` header or a `?secret=` query param. `503` if `CRON_SECRET` isn't
configured on the server; `403` if the secret is missing or wrong. `200` `{ "sent": <int> }` on
success — the number of digest emails sent. The reminder window's notion of "today" follows
`REMINDER_TIMEZONE` (IANA zone, default UTC), so the run time should suit that zone.

## LLM extraction schema

The parser forces Claude to call a `record_extraction` tool with this shape (validated by Pydantic):
```json
{
  "decisions": ["string"],
  "action_items": [
    {
      "description": "string",
      "owner": "string | null",
      "deadline": "YYYY-MM-DD | null",
      "status": "todo | in_progress | done",
      "confidence": 0.0,
      "source_decision": "string | null"
    }
  ]
}
```
`description`, `status`, and `confidence` are required per item; the rest default to null/`todo`.
`deadline` is inferred relative to the meeting date; `owner` is set only when a named person is
clearly responsible; `status` is inferred from the transcript.
