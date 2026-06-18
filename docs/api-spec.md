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
Returns `201` `{ "token": "<jwt>", "user": { "id", "email", "created_at" } }`. `409` if the email
already exists.

### `POST /auth/login`
Body `{ "email": "string", "password": "string" }` → `200` `{ "token", "user" }`; `401` on bad
credentials.

### `GET /auth/me`
Returns the current user (requires bearer). `401` if unauthenticated.

## Projects

A project object:
```json
{
  "id": 1, "name": "string", "description": "string",
  "created_at": "2026-06-17T09:30:00",
  "owner_user_id": 1,
  "access_level": "edit",
  "view_token": "string",
  "edit_token": "string | null"
}
```
`edit_token` is returned only to edit-level callers.

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
Update `name` / `description`. Requires edit access. Returns the project; `404`/`403` as above.

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
tasks).

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
Removes the task. Requires edit access. `204 No Content`; `404` if not found.

## Stakeholders

### `GET /stakeholders`
List stakeholders (alphabetical).

### `POST /stakeholders`
Body `{ "name": "string", "email": "string (optional)" }` → `201` stakeholder object.

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
