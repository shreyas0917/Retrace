# Architecture

Retrace Phase 8 adds the final engineering evidence UI on top of Phases 1–7.

## Evidence UI flow

```text
Query
  → Retrieval (chunks + scores)
  → Generation (answer / abstention)
  → Judges (relevance / faithfulness / contradiction)
  → Diagnosis (failure_code + rule_id)
  → Evidence refs
  → Evaluation / baseline / regression
  → Operations
```

## Frontend navigation

| View | Purpose |
| ---- | ------- |
| Investigate | Full diagnostic chain for one execution |
| Evaluations | Suite run, metrics, baseline, regression |
| Experiments | Experiment list + case → investigate |
| Operations | Health, metrics, signals, runbooks |

## Investigation API

`GET /api/v1/investigations/{execution_id}` aggregates:

- execution + generation metadata
- diagnosis + taxonomy failure description
- rule catalog entry (conditions — not LLM prose)
- enriched retrieval chunks (`retrieved` / `expected` / `relevant` / `distractor` / `missing`)
- judge results
- evidence rows
- timeline from stored latencies

Supporting:

- `GET /api/v1/rules` / `GET /api/v1/rules/{rule_id}`
- `GET /api/v1/runbooks` / `GET /api/v1/runbooks/{slug}`

## Ops flow (Phase 7)

```text
HTTP / RAG / diagnose / eval
 ↓
structured JSON logs (redacted)
 ↓
in-memory metrics
 ↓
GET /metrics · GET /api/v1/signals
 ↓
runbooks
 ↓
engineer action
```

## Correlation

```text
request_id → retrieval_trace_id → execution_id → failure_code / rule_id
experiment_id → case_id → execution_id → investigation
```

## Health

| Endpoint | Meaning |
| -------- | ------- |
| `/health/live` | Liveness |
| `/health/ready` | Postgres + Chroma |

## Limitations

- Metrics are in-memory (not durable telemetry)
- Offline fixture scores ≠ live-LLM robustness
- Diagnosis is a deterministic rule engine, not free-form LLM explanation

Phases 1–9 are complete. There is no Phase 10 in this project scope.

## Out of scope

Kubernetes, Datadog, Langfuse, Prometheus server, agents, auto-remediation.
