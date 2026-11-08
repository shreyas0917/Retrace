# Reference

Endpoints, CLI commands, configuration and repository layout. For what the
words mean, see [concepts.md](concepts.md).

## Authentication

Automation uses `Authorization: Bearer <API_KEY>`. The console signs in once
at `POST /api/v1/auth/session` and then uses a short-lived HttpOnly session
cookie; cookie-authenticated writes must send
`X-Requested-With: retrace-console`. Details: [security.md](security.md).

```bash
export API_KEY=<the API_KEY from .env>
BASE=http://localhost:8000

curl -s $BASE/health/ready

# Diagnose a trace from your own RAG app
curl -s -X POST $BASE/api/v1/traces \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  --data-binary @examples/traces/contradiction.json

# Run a query through Retrace's own RAG path, then diagnose it
curl -s -X POST $BASE/api/v1/generate \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"corpus_version_id": "<corpus_version_id>", "query": "What is the refund window?"}'
curl -s -X POST $BASE/api/v1/diagnose \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"execution_id": "<execution_id>"}'

# Everything about one execution
curl -s $BASE/api/v1/investigations/<execution_id> -H "Authorization: Bearer $API_KEY"
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/auth/session`, `/api/v1/auth/logout`, `GET /api/v1/auth/me` | Console session login, logout, state |
| `POST` | `/api/v1/traces`, `/api/v1/traces/batch` | Diagnose a trace from your own RAG app ([integrate.md](integrate.md)) |
| `POST` | `/api/v1/corpora`, `/api/v1/corpora/{id}/versions` | Create and ingest a corpus version |
| `POST` | `/api/v1/retrieve` | Retrieve top-k chunks with a trace and injection flags |
| `POST` | `/api/v1/generate` | Full RAG execution with tokens and cost |
| `POST` | `/api/v1/diagnose` | Run the rule engine on an execution |
| `GET` | `/api/v1/investigations/{execution_id}` | Aggregated investigation view |
| `POST` | `/api/v1/experiments` | Run a suite as an experiment |
| `GET` | `/api/v1/experiments/{id}/comparison` | Compare an experiment with the active baseline |
| `POST` | `/api/v1/baselines/promote` | Promote an experiment to the active baseline |
| `GET` | `/api/v1/metrics/durable`, `/metrics`, `/api/v1/signals`, `/api/v1/ops/summary` | Durable and in-memory metrics, signals, ops summary |
| `GET` | `/health/live`, `/health/ready` | Liveness; readiness (Postgres and Chroma) |

## CLI

Inside the backend container: `docker compose exec backend python -m app.cli.retrace <command>`.

| Command | Purpose |
| --- | --- |
| `diagnose --file trace.json [--batch traces.jsonl] [--fail-on CODES] [--json]` | Diagnose your own RAG traces in CI; exit 0 ok, 1 a `--fail-on` code matched, 2 error |
| `eval --suite planted_v1` | Run a suite, persist the experiment, gate against the baseline, exit 0/1/2 |
| `baseline promote <experiment_id>` | Accept an experiment as the active baseline |
| `benchmark report --suite heldout_v1 --calibrate-on calib_v1` | Per-class metrics, calibration and classifier comparison as Markdown |
| `retrieval-eval --corpus-dir /data/corpus/demo` | Chunking by retriever ablation with Recall@k, MRR, nDCG |
| `judges validate [--faithfulness-backend nli\|llm\|both]` | Judge agreement with labelled examples, consistency and prompt sensitivity |
| `telemetry prune [--days N] [--dry-run]` | Delete durable telemetry older than N days ([observability.md](observability.md#retention)) |

## Makefile

| Target | Action |
| --- | --- |
| `make demo` | Create `.env` if missing, start the stack, seed, post an example trace, print the console link |
| `make up` / `make down` | Build and start, or stop, all services |
| `make logs` | Follow backend logs |
| `make migrate` | Run Alembic migrations to head |
| `make seed` | Seed the demo corpus |
| `make eval` | Run an evaluation suite (`SUITE=planted_v1` by default) |
| `make test` | Run backend tests in the container |
| `make health` | Hit liveness and readiness endpoints |

## Configuration

Copy [`.env.example`](../.env.example) to `.env` (`make demo` does this and
generates `API_KEY`). The important groups:

| Variable | Purpose |
| --- | --- |
| `API_KEY` | Operator credential for Bearer calls and console login |
| `SESSION_SECRET`, `SESSION_TTL_MINUTES`, `COOKIE_SECURE` | Session cookie signing key, lifetime, Secure flag |
| `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `MAX_QUERY_CHARS`, `MAX_REQUEST_BYTES` | Abuse controls |
| `MAX_TRACE_CHUNKS`, `MAX_TRACE_CHUNK_CHARS`, `MAX_TRACE_ANSWER_CHARS`, `MAX_TRACE_BATCH` | Limits for external traces |
| `DATABASE_URL`, `POSTGRES_*`, `CHROMA_HOST`, `CHROMA_PORT` | Stores (Compose wires these) |
| `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`, `MODEL_TIMEOUT_SECONDS`, `MODEL_MAX_RETRIES`, `MODEL_CONNECT_TIMEOUT_SECONDS` | OpenAI-compatible LLM endpoint (generation and the LLM judges) |
| `FAITHFULNESS_BACKEND`, `NLI_MAX_PAIRS` | Faithfulness judge (`nli` or `llm`) and the NLI pair cap |
| `EMBEDDING_MODEL` | Pinned to `sentence-transformers/all-MiniLM-L6-v2` |
| `TELEMETRY_DURABLE`, `TELEMETRY_RETENTION_DAYS`, `TELEMETRY_PRUNE_ENABLED`, `PRICING_PATH`, `UVICORN_WORKERS` | Durable metrics and retention, cost table, worker count |
| `CORS_ORIGINS`, `LOG_LEVEL`, `ENVIRONMENT` | Console origins, logging, environment |

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI (Python 3.11), SQLAlchemy 2, Alembic, structlog, httpx |
| Database | PostgreSQL 16 (metadata, traces, experiments, durable telemetry) |
| Vector store | ChromaDB 0.5 |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` in-process; BM25 and hybrid retrievers in the ablation |
| Judges | LLM relevance and contradiction; NLI faithfulness with `cross-encoder/nli-deberta-v3-small` on CPU |
| LLM | Any OpenAI-compatible API; local Ollama for development |
| Frontend | React 18, TypeScript, Vite, Vitest |
| Packaging | Docker Compose (Postgres, Chroma, backend, nginx-served frontend) |

## Repository layout

```text
retrace/
├── backend/
│   ├── app/
│   │   ├── api/            # routers: auth, traces, corpus, retrieve, generate, diagnose, investigate, experiments, benchmark, health
│   │   ├── cli/            # retrace CLI: diagnose, eval, baseline, benchmark, retrieval-eval, judges, telemetry
│   │   ├── core/           # config, security, rate limit, hardening, injection, logging, redaction, metrics, telemetry, signals
│   │   ├── db/             # SQLAlchemy models and session
│   │   ├── schemas/        # Pydantic request/response models
│   │   └── services/       # ingestion, retrieval, generation, external traces, judges/, diagnosis/, eval/, metrics/
│   ├── alembic/            # migrations 001 to 008
│   ├── configs/            # thresholds per suite, calibration.json, pricing.yaml, observability signals
│   ├── datasets/           # suites, retrieval qrels, judge labels
│   └── tests/
├── frontend/               # React + Vite console
├── examples/traces/        # example traces for POST /api/v1/traces and retrace diagnose
├── scripts/                # demo, seed, suite builders, labelling, load test, dev_test.sh
├── docs/                   # concepts, integrate, architecture, benchmarks/, runbooks/, decisions
├── data/corpus/demo/       # 13 demo policy documents
└── docker-compose.yml · Makefile · .env.example · CHANGELOG.md · LICENSE
```
