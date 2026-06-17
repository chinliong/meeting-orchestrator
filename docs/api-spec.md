# API Specification

Base URL: `/api/v1`. Interactive docs (Swagger UI) are served at `/docs` when the backend runs.

All request/response bodies are JSON unless noted. Dates are ISO 8601 (`YYYY-MM-DD`).

## Health

### `GET /health`
Returns `{ "status": "ok" }`.

## Transcripts

### `POST /transcripts`
Submit raw transcript text for parsing. Synchronously runs the LLM and stores the extracted tasks.

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
Submit an audio/video file (`multipart/form-data`). Transcribed locally with Whisper, then parsed.

Form fields: `project_id` (int), `title` (string), `file` (the upload).

Responses: `201` (same shape as above) · `400` empty file · `404` unknown project ·
`503` if Whisper isn't installed.

### `GET /transcripts/{meeting_id}`
Returns the meeting's status and its extracted tasks (same object shape). `404` if not found.

## Tasks

### `GET /tasks`
Query params (all optional): `project_id`, `owner`, `status` (`todo|in_progress|done`),
`due_before`, `due_after`. Returns an array of task objects.

### `PATCH /tasks/{task_id}`
Update any of `description`, `owner`, `deadline`, `status`. Returns the updated task; `404` if not found.

### `DELETE /tasks/{task_id}`
Removes the task. `204 No Content`; `404` if not found.

## Projects

### `GET /projects`
List projects (newest first).

### `POST /projects`
Body `{ "name": "string", "description": "string (optional)" }` → `201` project object.

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
      "confidence": 0.0,
      "source_decision": "string | null"
    }
  ]
}
```
`description` and `confidence` are required per item; the rest default to null. `deadline` is
inferred relative to the meeting date; `owner` is set only when a named person is clearly responsible.
