# Runbook: Request error rate / not ready

## Signal

`REQUEST_ERROR_RATE` ALERT or `/health/ready` → `not_ready`

## Meaning

HTTP 5xx rate is high, or Postgres/Chroma checks failed. These are ops failures, not RAG diagnosis codes.

## Check

1. `GET /health/live` — process alive?
2. `GET /health/ready` — postgres / chroma
3. `GET /api/v1/status` (auth) — dependency details
4. Logs: `postgres_check_failed`, `chroma_unavailable`, unhandled exceptions

## Actions

- Restore Postgres / Chroma before investigating diagnosis quality
- Confirm Compose services are healthy
- After recovery, re-check `/api/v1/signals`
