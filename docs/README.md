# Documentation

## The system

| Document | What it covers |
|---|---|
| [architecture.md](architecture.md) | How the frontend, backend, database and external services fit together, and the data model |
| [api-spec.md](api-spec.md) | Every API endpoint, with its request and response |
| [meeting-assistant.md](meeting-assistant.md) | What the meeting assistant does, how it works, its limits, and how to turn it on |

## Evaluation

Start with **evaluation-report.md**; the others go deeper or cover a different part of the system.

| Document | Question it answers | Chosen for the app | Data |
|---|---|---|---|
| [evaluation-report.md](evaluation-report.md) | Which model extracts tasks from a transcript most accurately? | Gemini Flash (compared with Claude Sonnet and Claude Haiku) | 8 annotated test meetings written for this project (156 tasks), 8 runs per model |
| [evaluation-appendix.md](evaluation-appendix.md) | The method and every figure behind that report: per-condition results, deadline errors, the confidence score, limitations | - | Same 8 meetings |
| [asr-evaluation.md](asr-evaluation.md) | Which speech-to-text service transcribes recordings most accurately, and do the tasks still come out right from a recording? | Deepgram Nova-3 (compared with hosted and local Whisper) | 2 real meetings from the AMI Meeting Corpus: their recordings, AMI's manual transcripts and AMI's own action lists |
| [subtask-evaluation-report.md](subtask-evaluation-report.md) | Which model writes better subtask checklists? | Gemini Flash (compared with Claude Sonnet) | 24 tasks taken from the 8 test meetings (12 per test set), each breakdown scored against a rubric by an LLM judge |
| [agent-evaluation.md](agent-evaluation.md) | Part 1: should the meeting assistant extract a meeting's tasks, or the parser? Part 2: does it recognise tasks already on the board and suggest the right changes to them? | The parser extracts; the assistant reconciles | Part 1: the same 8 test meetings, each imported onto an empty board, 8 runs, scored with the parser evaluation's matcher. Part 2: 8 follow-up meetings written for this test, two for each short test meeting, with an answer key; 1 run |

Each evaluation page is generated from saved results by the script named at its top, so the
numbers on the page always match the raw results in `eval/`.
