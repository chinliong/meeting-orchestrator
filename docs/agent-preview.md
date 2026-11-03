# Local project assistant

The assistant, on in the deployed app (`render.yaml`) and opt-in locally, adds a floating assistant styled with the app's existing navy cards, blue accents,
typography and rounded controls. It answers questions about the selected project, proposes task
changes from chat, and reconciles a **new** meeting transcript with existing tasks.
A meeting's tasks always come from the evaluated parser, with their confidence scores; the assistant
reconciles them with the board rather than extracting tasks itself (see
[agent-evaluation.md](agent-evaluation.md) for why).
It uses `GEMINI_MODEL` and `GEMINI_API_KEY` from the app's current configuration. With no model
override, it uses `app.llm.gemini.DEFAULT_MODEL`. It never falls back to a different provider.
The existing extraction, summary and subtask pipelines remain independent.

## Try it

For your regular development app, set `ENABLE_MEETING_AGENT=true` in `backend/.env`
and `NEXT_PUBLIC_MEETING_AGENT_PREVIEW=true` in `frontend/.env.local`. Keep
`NEXT_PUBLIC_API_BASE=http://localhost:8000/api/v1`. Restart the standard backend and
frontend servers and open http://localhost:3000. This uses your existing development
database, accounts and boards. The model configuration remains the existing Gemini one.
These local environment files are ignored by Git; enabling them does not change deployment settings.

The isolated launcher below is optional. Stop it before running the regular frontend;
the two frontend processes use the same Next.js build directory. Its sample data stays
in `.local-agent/preview.db` and is not copied into the regular development database.

From the repository root, with the existing backend environment and frontend dependencies installed:

```bash
backend/.venv/bin/python scripts/agent_preview.py
```

The script prints a link to the sample board at **http://127.0.0.1:3100/app**. Open the full link
printed in the terminal (also saved in `.local-agent/preview-url.txt`) to access the sample board.
The API listens at `127.0.0.1:8100`. Both listeners are restricted to this computer.

1. Use the existing **New meeting** card: enter the title/date, then paste a transcript or upload a recording.
2. The meeting and new tasks save automatically. No confirmation opens when there are no updates to existing tasks.
3. If existing tasks would change, **Suggested changes** shows only those updates. Uncheck anything unwanted,
   then choose **Apply selected**. Closing the confirmation leaves existing tasks untouched; the meeting and new tasks stay saved.
4. Open the blue assistant button for questions about saved meetings or current tasks. Try
   “What is Priya working on?” and then “Move that task's deadline to this Friday.”
5. The board toolbar’s **Changes** menu shows an approval count and contains **Suggested changes** and **Recent changes**.
   Meeting batches open a review dialog. One or two chat changes are approved in the chat itself.
   **Recent changes** lists applied and undone changes only. Undoing approved updates preserves the imported
   meeting and its new tasks. The original import has its own receipt and can only be removed from
   **Recent changes**, after confirmation. Approved task changes enter the main Undo history,
   retaining earlier normal edits. Undo still checks affected tasks before reverting.

This works for a first meeting as well as a follow-up. On an empty board the assistant is not called:
the parser's tasks are saved as they are. Pasted text and transcribed audio/video take the same path.
Recordings process in the background; their existing-task updates open for review when processing finishes.
Pending updates remain in Changes if the browser closes before processing finishes. Ambiguous points appear
as clarification notes; they do not require a review form.

Example follow-up for the sample board:

```text
Alex: The landing page design is now finished and approved.
Priya: The accessibility audit is still in progress. Move its deadline to 6 November 2026; I am still the owner.
Sam: I will write the release notes by 5 November 2026. This is a new action.
```

The sample checks a completed design task, a moved audit deadline and a new release-notes task.
Ambiguous requests remain questions rather than automatic edits. An exact suggestion count is not a quality target.

The launcher uses `.local-agent/preview.db`, its own signing secret and synthetic seed data.
It reads only the Gemini key and model from `backend/.env`; it disables automatic dotenv loading
for the backend and disables email providers. It does not use the existing development or live
database. The frontend's API URL is overridden explicitly for this process. Stop both servers
with Ctrl+C; the preview database and review history persist for next time.

**Local app, hosted model:** chatting and reviewing send your messages, supplied transcript and selected project context
to Google's Gemini API using the existing API key, with normal API usage charges. The model itself
does not run on this computer. No push or deployment is part of this workflow.

## Interface

The launcher shows only its circular icon until hovered or focused. On desktop, opening chat
reserves a side column and narrows the board instead of covering it; smaller screens use a sheet.
The header is one row. Suggested changes and Recent changes share the board toolbar’s Changes menu, and
opening a review does not discard the conversation or close chat.

One or two chat changes show task titles, before/after values, evidence and Apply/Undo directly
in the conversation. Meeting batches use the selection dialog. Both use the same server apply
and undo endpoints. The main Undo/keyboard shortcut records approved task changes without clearing earlier
history; using Undo in a receipt removes only that action from the main stack. History remains
in browser memory and resets on a board/session switch as before.

Task sources appear as compact cards, each with one Evidence disclosure. Task IDs, model names
and tool traces are absent from the normal interface. Set `NEXT_PUBLIC_AGENT_DEBUG=true` before
starting/building the frontend to show model/tool diagnostics for evaluation. Copy and reading
position preservation remain available; retrying a failed request retains a separately typed draft.

Meeting suggestions remain available without a one-hour expiry. Changed tasks are disabled until
Refresh rechecks the stored transcript against current tasks. Refresh never imports a second
meeting or creates extra tasks. Chat suggestions retain an expiry and can also be refreshed from
the conversation. Relative dates remain anchored to the original meeting/request date. A source
meeting that was removed/edited must be supplied through New meeting again; the dialog links there.
Removed meetings’ unapproved changes leave the toolbar, while their audit details stay stored.

Removing a meeting import from Recent changes still requires explicit confirmation, with Keep
meeting focused first. Ordinary task-change undo preserves the meeting and its new tasks. Pasted
meetings use the same background summary job as the original parser.

## Design

Chat must retrieve fresh board context on every turn. It can retrieve project meetings and use
`query_tasks` for deterministic owner, status and deadline filtering. Source cards include exact
excerpts validated against tasks or meetings actually retrieved in that turn. Counts are calculated
in code; interpretation still depends on Gemini. The tool loop has no direct write capability.
Chat proposals must cite the user's own messages, and use the same explicit approval and undo
workflow as meeting reviews. Applying a chat proposal changes tasks without inventing a meeting.

Conversation text stays in browser memory and resets when switching projects or sessions or
reloading. Up to 12 prior messages accompany each request. Saved proposals and their supporting
user messages persist in the isolated database; ordinary chat answers do not. The assistant is
hidden in the cross-project search view. View-only collaborators can ask questions but cannot
create proposals or use the meeting-review controls. Chat uses the browser's local date for
relative-date requests; inspect the proposed absolute date before applying.


Every meeting is first parsed by the evaluated extraction parser. If the board has no tasks, its tasks
are the result and the agent is not called. Otherwise the agent receives them as numbered
`candidate_tasks`: it lists those that repeat or continue an existing task under `existing_items`, so
they are not added again, and proposes updates to existing tasks. Any new task it proposes itself
is ignored in a meeting review; the remaining candidates are added with their extraction score and
source decision. Each candidate matched to an existing task is named in a note after the import, so a
wrong match can be noticed and the task added by hand.

The board is sent with the meeting, so no model call is spent fetching it. The meeting-review agent
then has two tools: `read_meeting`, to retrieve an earlier meeting when it needs context, and
`finish_review`. Chat works the same way, with `query_tasks` in place of a board read. Its meeting index covers
task source meetings and the 30 most recently added completed meetings, including follow-ups that
only updated tasks. It has no write,
delete, email, shell or arbitrary network tool. Its multi-turn REST adapter retains Gemini's full
model content, including thought signatures and function-call IDs, between turns.

The output schema is strict. Server validation checks field types, valid dates, in-project task
IDs, distinct update targets, exact evidence excerpts, no-op edits, identical duplicate descriptions,
and attempts to change tasks sourced from a later meeting. A meeting review may change an existing
owner or deadline but not clear one; a cleared field is restored, and a suggestion whose only change
was clearing is dropped (chat may clear a field when asked to). After the exact-excerpt check, a quote
that starts partway through a turn gets its speaker's label added ("Priya: …", or "Speaker 2: …"
for a transcribed recording), taken from the nearest label above it; a header line such as
"Date:" adds none, so a quote is never attributed to an earlier speaker. New/reassigned owners
must appear in the labelled quote by full or first name, so "Jun will take it" supports Jun Tan
and a speaker's own "I'll do it" supports that speaker; empty owner strings become unassigned. Conservative token comparison
turns likely near-duplicate new tasks into questions rather than automatic additions. The model can correct rejected output
within a budget of six model calls and three minutes; it cannot retry indefinitely. Each API call
has a timeout of at most 90 seconds. There are at most 30 proposals, 200 board tasks, 60,000 input
transcript characters, and 160,000 characters of supplied data context. Oversized input is rejected
or additional context retrieval is refused, never silently presented as a complete review.

Proposals are persisted separately in `agent_reviews`, with the original transcript, before/after
fields, concise tool activity, model name and baseline fingerprint. No board writes occur during
generation. The `/parse` flow then saves the meeting and newly identified tasks, and persists a separate
`meeting_updates` draft for existing-task changes in one transaction. `/parse` never commits an
intermediate draft. After the paid call it rechecks current tasks: matching new work is withheld
with a question, and updates whose targets changed are withheld while the meeting and other new
tasks still save. Existing-task updates still require
explicit confirmation; they cannot be auto-applied by parsing. Applying accepts **only server-issued proposal IDs**, rechecks edit permissions and
expiry, and compares only each selected update target’s ID and four editable fields with its
stored before values. Unrelated tasks, checklist changes, attachments and meeting-title edits
do not block approval. New tasks are checked again for likely duplicates before saving. A conditional review-state update claims the draft, and the
selected task changes, saved meeting and receipt commit in one database transaction. Sequential
retries with the same selection return the existing receipt. A concurrent claim can return a
conflict; reopen the review to see its final state. The client does not automatically retry paid
reviews or mutations after a network failure.

Existing tasks retain their original source meeting; the review audit records the follow-up's
evidence. Newly created tasks reference the new meeting and keep the parser's confidence score and
source decision, shown at the top of the task's detail view (folded to three lines when long, speaker
names in bold), so a low score still marks the card "Check this". A task the assistant proposes from
chat has no extraction score: it stores `confidence` as null, its card shows no flag and its detail
view no confidence chip.
Applying task changes records an inverse in the board's Undo history and preserves earlier actions. Undo
checks affected tasks again and refuses to erase newer edits. Tasks that undo would delete
also receive content-level subtask/attachment checks. Older receipts keep their original stricter
board-wide undo check.

The interface is enabled only with `NEXT_PUBLIC_MEETING_AGENT_PREVIEW=true`; the backend requires
`ENABLE_MEETING_AGENT=true`. Both default to off locally; `render.yaml` sets both for the deployed
app. The local launcher sets both only for its child processes. The added table is created by the
existing SQLAlchemy table initialization; no existing columns are altered.

All endpoints are under `/api/v1/projects/{project_id}/agent` and require current project access. Review endpoints require edit access; chat permits view access:

| Method and path | Purpose |
|---|---|
| `POST /parse` | Parse a pasted transcript, save its meeting and new tasks, and return an optional existing-task update draft |
| `POST /recordings` | Upload audio/video, transcribe in the background, then save new tasks and withhold existing-task updates |
| `GET /recordings/{meeting_id}/result` | Retrieve the saved import, pending updates and clarification notes after a recording finishes |
| `POST /chat` | Ask a question with `message`, `current_date`, and optional `history`; may return a saved draft for editors |
| `POST /reviews` | Generate a draft from `title`, `meeting_date`, `transcript`, and optional `instructions` |
| `GET /reviews` | `view=history` returns up to 10 applied/undone changes; `view=pending` returns saved suggested changes for the toolbar |
| `GET /reviews/{id}` | Retrieve the proposal, source, activity and apply receipt |
| `POST /reviews/{id}/apply` | Apply the selected integer `proposal_ids` from the stored draft |
| `POST /reviews/{id}/refresh` | Recheck a draft against current tasks without importing another meeting or creating tasks |
| `POST /reviews/{id}/undo` | Reverse that batch if its board and meeting have not changed |

Chat is limited by `RATE_LIMIT_AGENT_CHAT` (default 30/hour). Text-parse entry points and assistant recordings
share `RATE_LIMIT_PARSE` (default 20/hour). Chat and refresh reserve six calls from the shared
`RATE_LIMIT_AI` allowance (default 30/hour), a meeting review seven (the parser's extraction plus six), and
`/parse` and `/recordings` eight, adding their background summary. On a board with no tasks the
assistant is not called, so a review reserves one call and `/parse` and `/recordings` two. The
reservation counts the bounded maximum, even if fewer calls are used. The app's health response advertises
`features.meeting_agent`; disabled review routes return 404.

## Validation and limits

The automated tests mock the model boundary, not the approval workflow:

```bash
cd backend
PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// .venv/bin/python -m pytest tests/test_agent.py tests/test_assistant.py -q
```

They cover read-only generation, model selection, thought-signature preservation, evidence and
target validation, speaker attribution and first-name owners, correction and tool limits, access isolation, expiry, stale data, selective
approval, idempotent apply, undo and preservation of subsequent work. Chat coverage includes
source validation, read-only access, user-message evidence, follow-ups, deterministic filtering,
project isolation, and applying/undoing changes without creating a meeting.

Exact evidence matching proves that a quote exists, **not** that a proposed interpretation is
correct. Semantic duplicate detection and relative-date reasoning still depend on Gemini and
human review. The assistant is a bounded agent, not an autonomous project manager. It accepts pasted
text and transcribed recordings. With the preview enabled, the frontend uploads recordings to
`POST /api/v1/projects/{project_id}/agent/recordings`; the backend checks the preview flag and
Gemini configuration before accepting that upload. The original `/transcripts/audio` endpoint
continues to use the original extraction flow. Both upload paths share the existing `RATE_LIMIT_AUDIO` allowance.

Before a production rollout, evaluate representative real follow-up meetings for correct task
matching, duplicate avoidance, field accuracy, unsupported changes, latency and cost. The current
implementation uses a synchronous bounded request; deployment would also need proxy-timeout and
worker-capacity checks, and stronger concurrency evaluation under production traffic. Chat drafts expire after one hour; the conversation offers Refresh. Meeting-update drafts do
not expire automatically. Stale meeting drafts stay visible with an explanation. Their changed targets are disabled while other
suggestions can still be applied. A removed/changed source meeting disables all its suggestions.
A retention policy would be needed for long-term use.

Design references: [Google's function-calling guide](https://ai.google.dev/gemini-api/docs/function-calling)
and [Anthropic's workflow/agent guidance](https://www.anthropic.com/research/building-effective-agents).

Malformed function calls can retry within the existing six-step/time budget; safety-filtered
responses are not retried. Chat history remains useful context, but earlier user instructions
already recorded in a proposal cannot be reused as authority for another edit. Explicitly
repeating the request in the current message is a new authorization. Duplicate transcripts use
the same Add again confirmation as the original parser, while duplicate-task checks still apply.

Owner-name presence and exact quotes do not prove correct attribution. Absolute/relative date
interpretation and semantic task identity still depend on the model and need evaluation; lexical
duplicate screening can flag distinct similar tasks and cannot catch every paraphrase.
