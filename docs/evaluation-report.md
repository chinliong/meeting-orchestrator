# Evaluation Report (Draft Template)

## Purpose

Assess the accuracy of the LLM transcript-parsing pipeline against manually annotated
meeting transcripts, and document prompt iterations and their effect on performance.

## Test Set

- Number of synthetic transcripts annotated: TBD
- Annotation method: manual labelling of decisions, action items, owners, deadlines
- Source: `data/annotated-test-set/`

## Metrics

- **Action item extraction precision/recall** (extracted vs. annotated)
- **Owner assignment accuracy**
- **Deadline inference accuracy** (exact match / within N days)
- **False positive rate** (hallucinated action items/decisions)

## Prompt Iterations

| Version | Change | Precision | Recall | Notes |
|---------|--------|-----------|--------|-------|
| v1      | Baseline prompt | - | - | - |
| v2      | TBD | - | - | - |

## Findings

_TODO: fill in after running evaluation script in `eval/`._

## Conclusions and Next Steps

_TODO_
