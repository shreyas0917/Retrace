<div align="center">

# Retrace

**AI reliability engineering for RAG pipelines.**

Retrace diagnoses *why* a retrieval-augmented generation answer failed, localizes the failure to retrieval, grounding, generation, abstention or infrastructure, and attaches reproducible evidence. It ships with evaluation suites, baselines, a regression gate and an engineering console.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-3776AB.svg?logo=python&logoColor=white)](backend/Dockerfile)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](backend/requirements.txt)
[![React 18](https://img.shields.io/badge/React-18-20232A.svg?logo=react&logoColor=61DAFB)](frontend/package.json)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white)](docker-compose.yml)
[![Version 0.9.0](https://img.shields.io/badge/version-0.9.0-4f7df3.svg)](docs/release.md)

</div>

---

Retrace is not a chatbot UI. It is an engineering tool for AI, ML, platform and reliability engineers who need to answer one question with evidence: **when a RAG answer is wrong, which stage broke, and how do we stop it regressing?**

```text
Query → Retrieval → Generation → Judges → Diagnosis → Evidence → Eval → Baseline → Ops
```

## Table of contents

- [Architecture](#architecture)
- [Features](#features)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Using Retrace](#using-retrace)
- [Evaluation, baselines and regression gates](#evaluation-baselines-and-regression-gates)
- [Real generation vs controlled evaluation](#real-generation-vs-controlled-evaluation)
- [Tests](#tests)
- [Repository structure](#repository-structure)
- [Configuration](#configuration)
- [Security notes](#security-notes)
- [Known limitations](#known-limitations)
- [Documentation](#documentation)
- [License](#license)

## Architecture

![Retrace system architecture: console and CLI drive a FastAPI backend and in-process services; a six-stage diagnostic pipeline persists to PostgreSQL and ChromaDB, is exercised by evaluation suites, experiments and a baseline regression gate, and feeds operations endpoints and runbooks.](docs/assets/architecture.svg)

**How a request flows**

1. **Entry.** The React console calls the FastAPI backend over HTTP with a Bearer token. The CLI (`python -m app.cli.retrace`) calls the same service layer in-process, so CI can run evaluations without the API.
2. **Diagnostic pipeline.** A query is retrieved against a versioned corpus in ChromaDB, answered (or abstained) by an OpenAI-compatible LLM, scored by three judges (relevance, faithfulness, contradiction), then passed through a deterministic rule engine that emits a `failure_code`, a `rule_id`, a confidence and evidence references. Every stage writes a trace.
3. **Investigation.** `GET /api/v1/investigations/{execution_id}` aggregates the execution, diagnosis, rule catalog entry, enriched retrieval chunks (`retrieved` / `expected` / `relevant` / `distractor` / `missing`), judge results, evidence rows and a latency timeline into one view.
4. **Evaluation.** Suites (`gold_v1`, `planted_v1`) run cases through the pipeline as experiments. A promoted experiment becomes the active baseline; later runs are compared against it and exit `0`, `1` or `2`.
5. **Operations.** Structured, redacted JSON logs feed in-memory metrics, `GET /metrics`, `GET /api/v1/signals` and readiness checks for PostgreSQL and Chroma. Signals link to runbooks.

**Correlation chain**

```text
request_id → retrieval_trace_id → execution_id → failure_code / rule_id
experiment_id → case_id → execution_id → investigation
```

Full details: [docs/architecture.md](docs/architecture.md) and [docs/decisions.md](docs/decisions.md).

## Features

| Area | What you get |
| --- | --- |
| Corpus and retrieval | Versioned ingest, chunking, `all-MiniLM-L6-v2` embeddings, Chroma top-k retrieval with traces |
| Generation | OpenAI-compatible LLM client (local Ollama or cloud), abstention handling, execution traces |
| Judges | Relevance, faithfulness and contradiction scoring with structured outputs |
| Diagnosis | Deterministic rule engine: ordered rules, failure taxonomy, confidence, evidence refs |
| Investigation | Single API and UI view of diagnosis, retrieval evidence, judges, timeline, runbooks and raw JSON |
| Evaluation | Reproducible suites with suite-hash integrity checks |
| Baselines and regression | Promote an experiment, gate later runs with CI-friendly exit codes |
| Operations | Liveness and readiness, in-memory metrics, signals, runbooks |
| Console | React UI with four views: Investigate, Evaluations, Experiments, Operations |

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI (Python 3.11), SQLAlchemy 2, Alembic, structlog |
| Database | PostgreSQL 16 |
| Vector store | ChromaDB 0.5 |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` (in-process) |
| LLM | Any OpenAI-compatible API; local Ollama recommended for development |
| Frontend | React 18, TypeScript, Vite, Vitest |
| Packaging | Docker Compose (Postgres, Chroma, backend, nginx-served frontend) |

## Quick start

### Prerequisites

- Docker Desktop (or a compatible Compose runtime)
- For local generation: [Ollama](https://ollama.com) with a model such as `llama3.2:latest`

```bash
ollama pull llama3.2:latest
```

### 1. Configure

```bash
cp .env.example .env
# Edit .env: set API_KEY and the LLM settings. Never commit .env.
```

The Compose defaults point the backend at Ollama on the host through Docker Desktop networking:

```text
MODEL_BASE_URL=http://host.docker.internal:11434/v1
MODEL_API_KEY=ollama
MODEL_NAME=llama3.2:latest
```

`API_KEY` is read by the backend and baked into the frontend image at build time as `VITE_API_KEY`, so the console works out of the box. After changing `API_KEY`, rebuild the frontend:

```bash
docker compose up -d --build frontend
```

### 2. Start

```bash
docker compose build
docker compose up -d
```

| Service | URL |
| --- | --- |
| API | http://localhost:8000 |
| Console | http://localhost:3000 |
| Chroma | http://localhost:8001 |
| PostgreSQL | localhost:5432 |

Confirm migrations are at head:

```bash
docker compose exec backend alembic current
# expect: 006_phase6_experiments_baselines (head)
```

### 3. Seed the demo corpus

```bash
docker compose exec backend python /scripts/seed_demo_corpus.py
# or: make seed
```

### Makefile shortcuts

| Target | Action |
| --- | --- |
| `make up` | Build and start all services |
| `make down` | Stop services |
| `make logs` | Follow backend logs |
| `make migrate` | Run Alembic migrations to head |
| `make seed` | Seed the demo corpus |
| `make eval` | Run an evaluation suite (`SUITE=planted_v1` by default) |
| `make test` | Run backend tests in the container |
| `make health` | Hit liveness and readiness endpoints |

## Using Retrace

All `/api/v1` routes except health, metrics and runbooks expect `Authorization: Bearer <API_KEY>`.

```bash
export API_KEY=your_api_key_here
BASE=http://localhost:8000

# Health
curl -s $BASE/health/live
curl -s $BASE/health/ready

# Run a query through the full RAG path and get an execution_id back
curl -s -X POST $BASE/api/v1/generate \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"corpus_id": "<corpus_id>", "query": "What is the refund window?"}'

# Diagnose that execution
curl -s -X POST $BASE/api/v1/diagnose \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"execution_id": "<execution_id>"}'

# Open the full investigation (diagnosis, evidence, judges, timeline)
curl -s $BASE/api/v1/investigations/<execution_id> -H "Authorization: Bearer $API_KEY"

# Rule catalog and runbooks
curl -s $BASE/api/v1/rules -H "Authorization: Bearer $API_KEY"
curl -s $BASE/api/v1/runbooks
```

Key endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/corpora` | Ingest and version a corpus |
| `POST` | `/api/v1/retrieve` | Retrieve top-k chunks with a trace |
| `POST` | `/api/v1/generate` | Full RAG execution (retrieve + generate) |
| `POST` | `/api/v1/diagnose` | Run the rule engine on an execution |
| `GET` | `/api/v1/investigations/{execution_id}` | Aggregated investigation view |
| `POST` | `/api/v1/experiments` | Run a suite as an experiment |
| `GET` | `/api/v1/experiments/{id}/comparison` | Compare an experiment with the active baseline |
| `POST` | `/api/v1/baselines/promote` | Promote an experiment to the active baseline |
| `GET` | `/api/v1/signals`, `/metrics`, `/api/v1/ops/summary` | Operational signals and metrics |
| `GET` | `/health/live`, `/health/ready` | Liveness; readiness (Postgres + Chroma) |

The console at http://localhost:3000 exposes the same flow in four views: **Investigate** (full diagnostic chain for one execution), **Evaluations** (suite runs, metrics, baseline, regression), **Experiments** (experiment list, case to investigation) and **Operations** (health, metrics, signals, runbooks).

## Evaluation, baselines and regression gates

```bash
# Run the controlled planted suite
docker compose exec backend python -m app.cli.retrace eval --suite planted_v1 --suite-version 1.0.0

# Promote a completed experiment to the active baseline
docker compose exec backend python -m app.cli.retrace baseline promote <experiment_id>

# Optional suite integrity check
docker compose exec backend python -m app.cli.retrace eval --suite planted_v1 --expect-hash sha256:<suite_hash>
```

Exit codes are designed for CI:

| Code | Meaning |
| --- | --- |
| `0` | Pass (meets baseline, or no baseline yet) |
| `1` | Regression against the active baseline |
| `2` | Evaluation, integrity, config or runtime error |

Clean-room validation script (uses a FakeLLM for the controlled generate path):

```bash
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/validate_phase9.py"
```

## Real generation vs controlled evaluation

Keep these two modes separate when reading results.

| Mode | What it uses | Purpose |
| --- | --- | --- |
| Real local LLM | Ollama or a cloud OpenAI-compatible model | Validate the actual generate, diagnose and investigate path |
| Controlled planted suite | Fixtures plus scripted or FakeLLM judges where designed | Validate deterministic diagnosis correctness (12 planted scenarios) |

Planted-suite accuracy is evidence that the rule engine is correct. It is not evidence of live-LLM robustness.

## Tests

```bash
# Backend (inside the container)
docker compose exec backend pytest -v

# Frontend (on the host)
cd frontend
npm install
npm test
npm run build
```

Expected at v0.9.0: 84 backend tests, 5 frontend tests, production build succeeds.

## Repository structure

```text
retrace/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI routers: corpus, retrieve, generate, diagnose, investigate, experiments, benchmark, health
│   │   ├── cli/            # retrace CLI: eval, baseline promote
│   │   ├── core/           # config, security, logging, redaction, metrics, signals, ops
│   │   ├── db/             # SQLAlchemy models and session
│   │   ├── schemas/        # Pydantic request/response models
│   │   └── services/       # ingestion, retrieval, generation, judges/, diagnosis/, eval/, investigation
│   ├── alembic/            # Migrations 001 to 006
│   ├── datasets/           # Evaluation suite definitions
│   ├── prompts/            # Generation and judge prompts
│   └── tests/              # pytest suite
├── frontend/               # React + Vite console: Investigate, Evaluations, Experiments, Operations
├── scripts/                # seed_demo_corpus, run_benchmark, validate_phase9, smoke scripts
├── docs/
│   ├── assets/             # Architecture diagram
│   ├── runbooks/           # Operational runbooks served by the API
│   └── architecture.md, decisions.md, development.md, demo.md, release.md
├── data/
│   ├── corpus/demo/        # Demo documents for the seed script
│   └── gold/ planted/ reports/ baselines/   # Local artifacts (gitignored except .gitkeep)
├── docker-compose.yml
├── Makefile
├── .env.example
└── LICENSE
```

## Configuration

Copy [`.env.example`](.env.example) to `.env`. The important groups:

| Variable | Purpose |
| --- | --- |
| `API_KEY` | Bearer token for the API; also baked into the frontend build |
| `DATABASE_URL`, `POSTGRES_*` | PostgreSQL connection (Compose wires these for you) |
| `CHROMA_HOST`, `CHROMA_PORT` | Vector store location |
| `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`, `MODEL_TIMEOUT_SECONDS` | OpenAI-compatible LLM endpoint |
| `EMBEDDING_MODEL` | Locked to `sentence-transformers/all-MiniLM-L6-v2`; do not substitute silently |
| `CORS_ORIGINS` | Allowed console origins |
| `LOG_LEVEL`, `ENVIRONMENT` | Logging and environment flags |

Never commit real secrets. Keep placeholders in documentation and examples.

## Security notes

- `.env` is gitignored; `.env.example` is the template.
- API routes expect `Authorization: Bearer <API_KEY>` except health, metrics and runbooks where designed.
- Logs redact sensitive headers and fields, but avoid putting secrets in queries or documents.

## Known limitations

- Controlled and offline evaluation fixtures are not proof of live-LLM robustness.
- Operational metrics are in-memory and reset on process restart.
- Retrace does not claim production-scale reliability, multi-tenant SaaS or auto-remediation.
- Local Ollama is for development and integration, not a production load claim.
- Out of scope: Kubernetes, Datadog, Langfuse, a Prometheus server, agents.

## Documentation

- [Architecture](docs/architecture.md)
- [Design decisions](docs/decisions.md)
- [Development guide](docs/development.md)
- [Demo walkthrough](docs/demo.md)
- [Release notes](docs/release.md)
- [Runbooks](docs/runbooks/README.md)

## License

MIT. See [LICENSE](LICENSE).
