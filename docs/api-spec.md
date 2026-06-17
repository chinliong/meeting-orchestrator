# API Specification (Draft)

Base URL: `/api/v1`

## Transcripts

### `POST /transcripts`
Submit a transcript for parsing.

Request:
```json
{
  "project_id": "string",
  "meeting_title": "string",
  "transcript_text": "string",
  "audio_file": "optional, multipart upload"
}
```

Response: `202 Accepted` with `meeting_id`, processing status.

### `GET /transcripts/{meeting_id}`
Returns parsing status and, once complete, the structured extraction result.

## Tasks

### `GET /tasks`
Query params: `project_id`, `owner`, `status`, `due_before`, `due_after`.

### `PATCH /tasks/{task_id}`
Update `status`, `owner`, `deadline`.

### `DELETE /tasks/{task_id}`

## Projects

### `GET /projects`
### `POST /projects`

## Stakeholders

### `GET /stakeholders`
### `POST /stakeholders`

## LLM Extraction Schema

```json
{
  "decisions": [{"summary": "string"}],
  "action_items": [
    {
      "description": "string",
      "owner": "string",
      "deadline": "ISO 8601 date or null",
      "confidence": "float (0-1)"
    }
  ]
}
```

_This spec is a starting point and should be refined once endpoints are implemented._
