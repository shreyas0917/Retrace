# Runbook: Retrieval miss rate high

## Signal

`RETRIEVAL_MISS_RATE` status `ALERT`

## Meaning

Diagnoses are frequently classifying as `RETRIEVAL_MISS` (gold evidence not in top-k).

This is a RAG quality / retrieval signal, not an infrastructure outage.

## Check

1. `GET /api/v1/signals` — confirm actual vs threshold
2. `GET /api/v1/metrics` — inspect `diagnosis.code.RETRIEVAL_MISS` and `diagnosis.total`
3. Pick a recent `execution_id` from logs (`request_id` → `execution_id`)
4. `GET /api/v1/executions/{id}` — inspect retrieved chunk IDs
5. Compare against gold `relevant_chunk_ids` if evaluating a suite case

## Actions

- Verify corpus version is READY and expected documents ingested
- Check `top_k` and chunking config
- Run `retrace eval --suite planted_v1` offline localization check
- Do not treat this as Postgres/Chroma failure unless readiness is also red
