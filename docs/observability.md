# Observability: durable telemetry, cost accounting, LLM resilience

Retrace v1.0 replaces "in-memory counters that vanish on restart" with a two-tier
design: a fast per-process view plus a durable Postgres-backed store that survives
restarts and is shared across uvicorn workers.

## Two tiers

| Tier | Where | Scope | Reset on | Used for |
|---|---|---|---|---|
| In-memory (`MetricsRegistry`) | process heap | one worker process | restart | `/metrics` top-level, live counters in the console, default `/api/v1/signals` |
| Durable (`metric_events` table) | Postgres | all workers, all restarts | never automatically (see Retention) | `durable_store`, `/api/v1/metrics/durable`, `ops/summary.metrics.durable_window`, `/api/v1/signals?source=durable` |

Every `MetricsRegistry.inc()` / `.observe()` still updates the in-memory view *and*
appends an event to a thread-safe `TelemetryBuffer` (`app/core/telemetry.py`).
The buffer is flushed with a single batched `INSERT` by:

- `RequestIdMiddleware` at the end of every HTTP request (off the event loop via a
  thread; the request's own `http.request` latency is included),
- the FastAPI lifespan shutdown,
- `app.core.telemetry.flush_telemetry()` for CLI / evaluation paths that do not go
  through HTTP.

Flush failures are logged (`telemetry_flush_failed`) and never surface to the
request; rows are re-queued in a bounded buffer (20 000 events, oldest dropped and
counted in `TelemetryBuffer.dropped`). `TELEMETRY_DURABLE=false` disables every DB
write; the API then reports `{"available": false, "reason": "telemetry_disabled ..."}`.

### Schema (migration `007_telemetry_cost`)

```
metric_events(
  id bigserial primary key,
  ts timestamptz not null default now(),     -- ix_metric_events_ts
  kind text not null,                         -- 'counter' | 'latency'
  name text not null,                         -- ix_metric_events_name, ix_metric_events_name_ts (name, ts)
  value double precision not null,
  labels jsonb null,
  request_id text null                        -- correlation with structlog / X-Request-ID
)
execution_traces + cost_usd double precision null, pricing_version text null
```

One row per event (not pre-aggregated) keeps writes trivial and lets the
aggregates be computed exactly for any window.

### Aggregation

`durable_snapshot(db, window_minutes)` runs three grouped queries over the trailing
window (default 1440 min, max 43200 = 30 days):

- counters: `SUM(value)` per name,
- latencies: `COUNT`, `AVG`, `percentile_cont(0.5 / 0.95 / 0.99) WITHIN GROUP`, `MAX`,
- window metadata (event count, oldest/newest ts).

It returns the same `counters` / `latencies` / `derived` keys as the in-memory
snapshot so `evaluate_signals()` runs unchanged on either source, plus
`tokens`, `cost`, `window_minutes`, `source: "postgres"`, `durable: true`.

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /metrics`, `GET /api/v1/metrics` `?window_minutes=` | in-memory snapshot (`durable: false`, `source: "in-memory"`) plus `durable_store` (the durable snapshot, or `{available: false, reason}`) |
| `GET /api/v1/metrics/durable?window_minutes=` | only the durable snapshot |
| `GET /api/v1/signals?source=memory\|durable&window_minutes=` | signal rows; `metrics_source` says which store was evaluated (durable falls back to in-memory when unavailable) |
| `GET /api/v1/ops/summary?window_minutes=` | existing keys unchanged; adds `metrics.source`, `metrics.durable_available`, `metrics.durable_window` (p50/p95/p99 http latency, request error rate, requests, 5xx, LLM retries/failures, token totals, estimated cost) |

Backward compatibility: `metrics.durable` in `/metrics` and `ops/summary` still
describes the in-memory snapshot and stays `false`; use `durable_available` /
`durable_store.available` for the Postgres store.

## Metric names

| Name | Kind | Emitted by |
|---|---|---|
| `http.requests_total`, `http.requests_success`, `http.requests_4xx`, `http.requests_5xx`, `http.requests_failed` | counter | `RequestIdMiddleware` |
| `http.request` | latency (ms) | `RequestIdMiddleware` |
| `retrieval.attempts`, `retrieval.empty` / `retrieval` | counter / latency | `ops.record_retrieval` |
| `generation.attempts`, `generation.success`, `generation.failures`, `generation.timeout` / `generation` | counter / latency | `ops.record_generation` |
| `generation.prompt_tokens`, `generation.completion_tokens`, `generation.tokens_total` | counter | `ops.record_generation` (token usage) |
| `generation.cost_usd_micros` | counter (integer micro-dollars) | `ops.record_generation` |
| `llm.attempts`, `llm.retries`, `llm.failures`, `llm.timeouts` | counter | `OpenAICompatibleProvider` |
| `judge.attempts`, `judge.success`, `judge.timeout`, `judge.malformed`, `judge.type.<type>` / `judge`, `judge.<type>` | counter / latency | `ops.record_judge` |
| `diagnosis.total`, `diagnosis.code.<FAILURE_CODE>`, `diagnosis.rule.<rule>`, `diagnosis.layer.<layer>` / `diagnosis` | counter / latency | `ops.record_diagnosis` |

Derived rates (both tiers): `request_error_rate`, `retrieval_empty_rate`,
`generation_timeout_rate`, `judge_timeout_rate`, `judge_malformed_rate`,
`retrieval_miss_rate`.

## Cost model

- `backend/configs/pricing.yaml` (override with `PRICING_PATH`) lists USD per 1M
  prompt / completion tokens per model, an explicit `default` of 0, and
  zero-priced entries for local Ollama-style models. **Values are illustrative;
  verify with your provider.**
- Matching: exact model name, then longest prefix (`gpt-4.1-mini-2025-04-14` ->
  `gpt-4.1-mini`, `llama3.2:latest` -> `llama3.2`), then `default`.
- `app/services/pricing.py`: `load_pricing(path|None)`,
  `estimate_cost_usd(model, prompt_tokens, completion_tokens) -> float | None`
  (None only when the provider returned no usage), `pricing_version()`.
- `run_rag` persists `ExecutionTrace.cost_usd` and `pricing_version`, and
  `record_generation` adds `generation.cost_usd_micros` (integer micro-dollars so
  the counter stays additive and exact across processes). The durable snapshot
  reports `cost.usd = sum(micros) / 1e6`.
- Caveats: the estimate uses the provider's reported usage (Ollama reports
  tokens; some proxies do not); it ignores cached-input discounts, batch pricing
  and judge-call tokens (judges run through separate code paths); a missing or
  invalid pricing file degrades to a zero-cost table with version
  `pricing.builtin-zero`.

## LLM resilience (`app/services/llm_client.py`)

- One shared pooled `httpx.Client`; separate connect
  (`MODEL_CONNECT_TIMEOUT_SECONDS`, default 10 s) and read timeouts.
- The per-call timeout (`MODEL_TIMEOUT_SECONDS`) is the *total* budget; each
  attempt's read timeout is clipped to the remaining budget, and a retry is only
  scheduled when its backoff still fits inside the budget.
- Retries (`MODEL_MAX_RETRIES`, default 2; exponential backoff from
  `MODEL_RETRY_BACKOFF_SECONDS` with jitter; `Retry-After` honoured when <= 30 s)
  only on transport errors and HTTP 429 / 500 / 502 / 503 / 504. No retry on other
  4xx, on malformed bodies, or on timeouts (a timeout already consumed the budget).
- Error contract unchanged: `GenerationTimeoutError` (504, `GENERATION_TIMEOUT`,
  "LLM request timed out") and `GenerationError` (502, `GENERATION_FAILED`,
  "LLM request failed" / "LLM provider returned an error" / "LLM authentication
  failed" / "LLM returned a malformed response"); `details.attempts` is added.
- Testable via `OpenAICompatibleProvider(settings, transport=httpx.MockTransport(...))`
  or the module hook `set_llm_transport()`.

## Multiple uvicorn workers

`UVICORN_WORKERS` (default 1) is honoured by the Docker entrypoint. With more than
one worker each process has its own in-memory metrics snapshot and its own
in-memory rate limiter state, so `/metrics` top-level numbers and `ops/summary`
live counters depend on which worker answered; the durable store is shared and
is the view to trust in that configuration. Rate limits become "per worker".

## Retention

There is **no automatic pruning**. At roughly 10 events per request a steady
10 req/s produces about 8.6 M rows/day, so prune or roll up on a schedule you
control. Options:

```sql
-- keep 30 days (run from cron / a Postgres pg_cron job / a CI step)
DELETE FROM metric_events WHERE ts < now() - interval '30 days';

-- optional: roll up before deleting
CREATE TABLE IF NOT EXISTS metric_events_daily AS
SELECT date_trunc('day', ts) AS day, kind, name,
       count(*) AS n, sum(value) AS total,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY value) AS p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY value) AS p95,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY value) AS p99
FROM metric_events GROUP BY 1, 2, 3 WITH NO DATA;
INSERT INTO metric_events_daily
SELECT date_trunc('day', ts), kind, name, count(*), sum(value),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY value),
       percentile_cont(0.95) WITHIN GROUP (ORDER BY value),
       percentile_cont(0.99) WITHIN GROUP (ORDER BY value)
FROM metric_events WHERE ts < now() - interval '30 days' GROUP BY 1, 2, 3;
DELETE FROM metric_events WHERE ts < now() - interval '30 days';
```

CLI-less alternative from the compose stack:

```sh
docker compose exec postgres psql -U retrace -d retrace \
  -c "DELETE FROM metric_events WHERE ts < now() - interval '30 days';"
```

For very high volume, convert `metric_events` to a partitioned table by `ts`
(monthly) and drop old partitions instead of deleting rows.

## Testing across restarts and under failure

- `backend/tests/test_telemetry.py`: events flushed to Postgres; a fresh
  `MetricsRegistry` (restart simulation) sees nothing while the durable snapshot
  still has the counters and latencies; p50/p95/p99 checked against
  `percentile_cont` on 1..100; cost math and prefix matching; token/cost counters
  and `ExecutionTrace.cost_usd` after a FakeLLM generation; endpoint contracts;
  disabled and DB-error paths.
- `backend/tests/test_resilience.py`: retry on 503 then success, give-up after
  `MODEL_MAX_RETRIES`, no retry on 4xx, 429 + `Retry-After`, timeout ->
  `GenerationTimeoutError` and a persisted `GENERATION_TIMEOUT` trace via the API,
  20 concurrent `/api/v1/generate` calls, Chroma failure -> 503 + `not_ready`,
  DB failure -> 500 `DATABASE_ERROR`.
- `scripts/load_test.py` + `docs/benchmarks/load_test.md`: measured throughput
  and p50/p95/p99 on this machine.
