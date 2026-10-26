# Load test — Retrace backend (v1.0)

Measured with `scripts/load_test.py` (threads + httpx, fixed request count at a
fixed concurrency, 5 warm-up requests excluded) against the compose stack on
2026-10-25/26. Raw JSON reports: `data/reports/load_*.json`.

## Machine context

- Docker Desktop on Windows 11 (WSL2 backend); client and server on the same laptop.
- Backend container: `nproc` = 8, single uvicorn worker (`UVICORN_WORKERS=1`),
  Python 3.11, in-process MiniLM (`all-MiniLM-L6-v2`) query embeddings on CPU
  (no GPU), Chroma 0.5.23 and Postgres 16 as sibling containers.
- Durable telemetry enabled (`TELEMETRY_DURABLE=true`): every request ends with
  one batched INSERT into `metric_events`.
- Rate limiter raised to 100000/min for the run via a compose override (the
  default 120/min per key would 429 a 300-request burst by design).
- `/health/ready` is not a no-op: it runs `SELECT 1` on Postgres and a Chroma
  heartbeat per call.
- Demo corpus (`scripts/seed_demo_corpus.py`): 11 markdown policies, READY version.
- Generation: Ollama `llama3.2:latest` on the host CPU via
  `http://host.docker.internal:11434/v1`.
- Background load on the same host during the run: unrelated project containers
  (including a Kafka test stack at well over one core) and, for part of the
  window, an Ollama judge-validation run. Absolute latencies are therefore
  pessimistic; the error-rate and saturation-shape conclusions are the
  transferable part. Re-run on an idle machine for capacity numbers.

## Results

| endpoint | concurrency | requests | req/s | error rate | p50 ms | p95 ms | p99 ms | max ms |
|---|---|---|---|---|---|---|---|---|
| ready | 10 | 300 | 19.12 | 0.00% | 479.8 | 959.1 | 1235.5 | 1380.1 |
| ready | 25 | 300 | 29.67 | 0.00% | 808.6 | 1270.2 | 1621.4 | 1746.1 |
| retrieve | 10 | 300 | 6.79 | 0.00% | 1346.6 | 2348.8 | 2831.7 | 3042.7 |
| retrieve | 25 | 300 | 6.08 | 0.00% | 3473.4 | 7476.5 | 8207.1 | 9797.3 |
| generate (Ollama, CPU) | 2 | 4 | 0.03 | 0.00% | 64990.0 | 79309.2 | 79563.9 | 79627.6 |

All 1204 requests returned 2xx: no 5xx, no timeouts, no connection errors at
any tested concurrency.

## Interpretation (honest)

- **Retrieval saturates at roughly 6-7 req/s on this box.** Throughput is
  flat between concurrency 10 and 25 while p50 latency rises from 1.3 s to
  3.5 s: the extra concurrency only queues. The bottleneck is CPU-bound query
  embedding (MiniLM in-process, sync endpoint on a single worker) plus the
  Chroma round trip; the system degrades gracefully (latency grows, nothing
  fails) rather than erroring.
- **Readiness is ~20-30 req/s**, not thousands, because each probe performs
  two real dependency checks plus the telemetry flush, all through Docker
  Desktop's Windows networking stack. Treat it as a dependency check, not a
  liveness ping (`/health/live` is the cheap one).
- **Generation is dominated by the LLM.** 65-80 s per answer is Ollama
  running an 8B-class model on CPU with two concurrent requests (Ollama
  serializes them); Retrace adds ~1.5 s of retrieval on top. The numbers are
  included to show the pipeline holds under concurrent generation (all traces
  persisted, no timeouts within the 120 s budget), not as a model benchmark.
- Latency percentiles are client-side wall-clock, so they include the
  localhost/Docker hop. The server-side view over the same period from
  `GET /api/v1/ops/summary?window_minutes=120` (durable store, Postgres)
  showed `http.request` p50 448 ms / p95 3662 ms / p99 6413 ms over 2005
  requests, plus 21 5xx and 36 LLM retries that came from a concurrent LLM
  benchmark run by another process against the same stack: the durable store
  aggregates across processes and across the backend restart that happened
  mid-session, which is the point of it.

## What would move the numbers

1. `UVICORN_WORKERS=4` (now supported by the entrypoint) to parallelise the
   CPU-bound embedding across cores; the durable store stays correct, the
   in-memory snapshot and rate limiter become per-process.
2. Embedding query cache / batching, or an external embedding service.
3. Running the client outside Docker Desktop's NAT (Linux host) typically
   removes several hundred ms from every percentile here.

## Reproduce

```sh
docker compose up -d --build backend
API_KEY=... docker compose exec -e API_KEY backend python /scripts/seed_demo_corpus.py
API_KEY=... python scripts/load_test.py --endpoint ready    --concurrency 10 --requests 300
API_KEY=... python scripts/load_test.py --endpoint retrieve --concurrency 25 --requests 300
API_KEY=... python scripts/load_test.py --endpoint generate --concurrency 2  --requests 10
```

Set `RATE_LIMIT_PER_MINUTE` high for the backend first, or the limiter will
(correctly) return 429s.
