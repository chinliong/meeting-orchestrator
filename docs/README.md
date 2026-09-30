# Documentation

## The system

| Document | What it covers |
|---|---|
| [architecture.md](architecture.md) | How the frontend, backend, database and external services fit together, and the data model |
| [api-spec.md](api-spec.md) | Every API endpoint, with its request and response |

## Evaluation

Start with **evaluation-report.md**; the others go deeper or cover a different part of the system.

| Document | Question it answers | Data |
|---|---|---|
| [evaluation-report.md](evaluation-report.md) | How accurately are tasks extracted from a transcript, and which model should the system use? | 8 annotated test meetings written for this project (156 tasks), 8 runs per model |
| [evaluation-appendix.md](evaluation-appendix.md) | The method and every figure behind that report: per-condition results, deadline errors, the confidence score, limitations | Same 8 meetings |
| [asr-evaluation.md](asr-evaluation.md) | How accurately are recordings transcribed, and do the tasks still come out right from a recording? | 2 real meetings from the AMI Meeting Corpus: their recordings, AMI's manual transcripts and AMI's own action lists |
| [subtask-evaluation-report.md](subtask-evaluation-report.md) | How good are the AI-suggested subtask checklists? | 24 tasks taken from the 8 test meetings (12 per test set), each breakdown scored against a rubric by an LLM judge |

Each evaluation page is generated from saved results by the script named at its top, so the
numbers on the page always match the raw results in `eval/`.
