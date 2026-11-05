# Meeting assistant

The meeting assistant does two things on a board:

- **Reconciles a new meeting with the board.** The evaluated parser still extracts every meeting's
  tasks. The assistant then works out which of them are already on the board, so they are not
  added twice, and suggests changes to existing tasks (a new status, owner or deadline) for you to
  approve.
- **Answers questions in chat** about the board and its meetings, and can suggest task changes
  when you ask for them.

It runs on Gemini (`GEMINI_MODEL`, `GEMINI_API_KEY`). Why extraction stays with the parser is in
[agent-evaluation.md](agent-evaluation.md); how well the assistant reconciles a follow-up meeting
with the board is measured in [reconciliation-evaluation.md](reconciliation-evaluation.md).

## Using it

**Adding a meeting.** Use the **New meeting** card as usual (paste a transcript or upload a
recording). The meeting and its new tasks are saved straight away. On an empty board the
assistant is not called. On a board with tasks, any suggestions open in a review:

- **Suggested changes** to existing tasks are selected; deselect any you don't want.
- **Possible duplicates** (collapsed) are extracted tasks that match one already on the board, or
  repeat another task from the same meeting almost word for word. They are not added or selected;
  select any that are really new to add them. When a meeting has only these, they wait under
  **Changes**.
- **Apply N** applies what is selected and dismisses the rest. With nothing selected it reads
  **Dismiss all**. **Not now** keeps everything waiting under **Changes**.

Recordings are processed in the background; their review opens when they finish.

**The Changes menu** on the board toolbar counts suggestions waiting for you and holds:

- **Suggested changes** waiting for approval.
- **Recent changes**, the last 10 entries: meetings *Added* or *Removed*, and suggestions
  *Applied*, *Dismissed* or *Undone*. An undone entry can be opened again with **Review again**,
  with the earlier choices selected. A meeting is removed with **Remove meeting…**, after
  confirmation.

**Undo.** Applied suggestions can be undone from the review, from the board's Undo button
(⌘Z / Ctrl+Z) or from Recent changes. Undo refuses if a task has been edited since, so newer work
is never overwritten.

**Chat.** Open the assistant button in the corner and ask, for example, "What is Priya working
on?" or "What's overdue?". Counts are calculated by code; answers cite the tasks or meeting
lines they rely on. Ask for a change ("Move that deadline to this Friday") and it is proposed for
approval in the chat. View-only users can ask questions but cannot change anything.

## How it works

1. The parser extracts the meeting's tasks, with confidence scores and source decisions.
2. If the board has tasks, the assistant receives the meeting, the board and those tasks as
   numbered candidates. It may read earlier meetings for context, then submits a review: which
   candidates repeat existing tasks, and which existing tasks the meeting changes.
3. The server checks the review before saving anything, and returns any rejection to the model to
   correct. Every suggestion must:
   - quote an exact line of the new transcript (labelled with its speaker, e.g. "Priya: …");
   - refer to a real task on this board and change at least one field;
   - name a new or changed owner in that quote (a first name, or the speaker's own "I'll do it",
     counts);
   - not erase an owner or deadline the meeting did not mention, and not change work from a
     later meeting.
4. New tasks are saved with their parser score and source. Suggestions are stored in the
   `agent_reviews` table and applied only when you approve them, in one transaction that refuses
   tasks edited since the suggestion was made.

The assistant has no tool that writes, deletes or sends anything; it can only read and suggest.
Chat works the same way, with a task filter tool for exact counts.

## Limits

| Limit | Value |
|---|---|
| Model calls per review or chat message | 6, within 3 minutes (90 seconds per call) |
| Suggestions per review | 30 |
| Board size | 200 tasks |
| Transcript length | 60,000 characters when pasted. Recordings may be longer; on a board with tasks, the transcript and board together must fit in 160,000 characters |
| Meetings it can read | Each task's source meeting plus the 30 most recent |
| Chat history sent | The last 12 messages |
| Chat suggestions | Expire after an hour; meeting suggestions do not expire |

Rate limits: chat 30 messages an hour; imports share the parse limit (20 an hour). Each request
reserves its maximum AI calls from the shared 30-an-hour allowance: 6 for chat, 7 for a review, 8
for an import (2 on an empty board, where the assistant is not called).

## Turning it on

The assistant needs both settings:

| Where | Setting |
|---|---|
| Backend (`backend/.env`, or the Render service) | `ENABLE_MEETING_AGENT=true` |
| Frontend (`frontend/.env.local`, or the Render site) | `NEXT_PUBLIC_MEETING_AGENT_PREVIEW=true` |

Both are off by default locally. The frontend setting is built into the site, so changing it on
Render needs a rebuild. `GET /api/v1/health` reports `features.meeting_agent`; when it is off the
assistant's routes return 404. `NEXT_PUBLIC_AGENT_DEBUG=true` shows model and tool details in the
interface, for evaluation.

**Sample board.** To try it without touching your own data, run from the repository root:

```bash
backend/.venv/bin/python scripts/agent_preview.py
```

It opens a sample board at http://127.0.0.1:3100/app (API on port 8100), stored in
`.local-agent/preview.db`. Stop your regular frontend first, as both use the same build folder.
A follow-up to paste:

```text
Alex: The landing page design is now finished and approved.
Priya: The accessibility audit is still in progress. Move its deadline to 6 November 2026; I am still the owner.
Sam: I will write the release notes by 5 November 2026. This is a new action.
```

Using the assistant sends the transcript and board to Google's Gemini API, with normal API
charges.

## Tests and known limits

```bash
cd backend
PYTHON_DOTENV_DISABLED=1 DATABASE_URL=sqlite:// .venv/bin/python -m pytest tests/test_agent.py tests/test_assistant.py -q
```

The tests replace the model with fixed responses and cover the checks, approval, undo, review
again and access rules. Limits that remain:

- An exact quote proves the line exists, not that the suggestion reads it correctly; that is why
  every change needs approval.
- Reconciliation was measured on eight follow-up meetings written for the test, where each change
  is stated plainly ([reconciliation-evaluation.md](reconciliation-evaluation.md)); real meetings
  are messier.
- Two people with the same first name in one meeting can confuse the owner check.

The endpoints are listed in [api-spec.md](api-spec.md#meeting-assistant).
