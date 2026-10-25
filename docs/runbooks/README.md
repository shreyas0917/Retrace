# Runbook index

Operational runbooks for Retrace Phase 7 signals.

| Signal / condition | Runbook |
| ------------------ | ------- |
| Retrieval miss rate | [retrieval-miss-rate.md](retrieval-miss-rate.md) |
| Generation timeout | [generation-timeout.md](generation-timeout.md) |
| Judge malformed | [judge-malformed.md](judge-malformed.md) |
| Request errors / not ready | [request-errors-readiness.md](request-errors-readiness.md) |

Correlation path:

```text
request_id → retrieval_trace_id → execution_id → failure_code / rule_id
```

Evaluation path:

```text
experiment_id → case_id → execution_id → diagnosis
```
