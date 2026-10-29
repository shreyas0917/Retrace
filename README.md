<div align="center">

# Retrace

**AI reliability engineering for RAG pipelines.**

Retrace diagnoses *why* a retrieval-augmented generation answer failed, localizes the failure to retrieval, grounding, generation, abstention or infrastructure, attaches reproducible evidence and a calibrated confidence, and ships the measurements that back every claim: a 160-case held-out benchmark, a retrieval ablation, judge validation, durable telemetry and a load test.

[![CI](https://github.com/shreyas0917/Retrace/actions/workflows/ci.yml/badge.svg)](https://github.com/shreyas0917/Retrace/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-3776AB.svg?logo=python&logoColor=white)](backend/Dockerfile)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg?logo=fastapi&logoColor=white)](backend/requirements.txt)
[![React 18](https://img.shields.io/badge/React-18-20232A.svg?logo=react&logoColor=61DAFB)](frontend/package.json)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED.svg?logo=docker&logoColor=white)](docker-compose.yml)
[![Version 1.0.0](https://img.shields.io/badge/version-1.0.0-4f7df3.svg)](CHANGELOG.md)
[![Held-out accuracy 98.1%](https://img.shields.io/badge/held--out%20accuracy-98.1%25-3bbf72.svg)](docs/benchmarks/heldout_v1.md)

</div>

---

Retrace is not a chatbot UI. It is an engineering tool for AI, ML, platform and reliability engineers who need to answer one question with evidence: **when a RAG answer is wrong, which stage broke, how sure are we, and how do we stop it regressing?**

```text
Query → Retrieval → Generation → Judges → Diagnosis (rule · calibrated confidence · explanation)
      → Evidence → Held-out eval · Baseline gate → Durable ops metrics
```

## Table of contents

- [What the measurements say](#what-the-measurements-say)
- [Architecture](#architecture)
- [Features](#features)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Using Retrace](#using-retrace)
- [Evaluation, benchmarks and regression gates](#evaluation-benchmarks-and-regression-gates)
- [Retrieval quality](#retrieval-quality)
- [Judge validation](#judge-validation)
- [Observability, cost and resilience](#observability-cost-and-resilience)
- [Security](#security)
- [Tests](#tests)
- [Repository structure](#repository-structure)
- [Configuration](#configuration)
- [Known limitations](#known-limitations)
- [Documentation](#documentation)
- [License](#license)

## What the measurements say

Every number below comes from a committed, reproducible report. Commands to regenerate them are in each linked document.

| Question | Result | Report |
| --- | --- | --- |
| How accurate is the diagnosis engine on cases it was not developed against? | 98.1% lenient / 93.1% strict accuracy, macro-F1 0.947 on 160 held-out cases across 12 failure classes; all 3 misses are deliberate boundary cases, and the engine deferred them as `DIAGNOSIS_UNCERTAIN` (100% selective accuracy at 98.1% coverage) | [heldout_v1.md](docs/benchmarks/heldout_v1.md) |
| Is its confidence calibrated? | Expected calibration error 0.128 → 0.004 and Brier 0.047 → 0.011 after histogram calibration fitted on a disjoint 80-case suite | [heldout_v1.md](docs/benchmarks/heldout_v1.md#confidence-calibration) |
| How do the rules compare with other classifiers on identical inputs? | Rule engine 98.1% · heuristic baseline 48.1% · majority 12.5% · LLM classifier (local `llama3.2`, 3B) 40.6%, macro-F1 0.42, 9 s per case vs 0.3 ms | [heldout_v1.md](docs/benchmarks/heldout_v1.md#classifier-comparison-on-identical-signal-bags) |
| Is retrieval actually good? | Production config (512/64 chunks, MiniLM dense): Recall@5 0.947, MRR 0.849, nDCG@10 0.869 on 82 answerable queries over 13 documents; BM25 0.890 / 0.816 / 0.830; best measured: 1024/128 hybrid with `bge-small` at Recall@5 0.953, MRR 0.919, nDCG@10 0.928 | [retrieval_ablation.md](docs/benchmarks/retrieval_ablation.md) |
| Can the LLM judges be trusted? | Measured, not assumed: against the full 66 labelled examples (282 calls, zero schema failures) with a local `llama3.2` (3B) the contradiction judge reaches kappa 0.78, the relevance judge kappa 0.69 per chunk but only 29% accuracy on "context sufficient", and the faithfulness judge kappa 0.02 (it returns a near-zero score even for fully supported answers); prompt rewording flips 13 to 20% of relevance verdicts | [judge_validation.md](docs/benchmarks/judge_validation.md) |
| Does it hold up under load and failure? | 0% errors at concurrency 25; retrieval saturates at 6 to 7 req/s on one CPU-bound worker (p95 2.3 s at c=10); fault-injection tests for LLM 5xx/429/timeouts, 20 concurrent generations, Chroma outage and database errors | [load_test.md](docs/benchmarks/load_test.md), `backend/tests/test_resilience.py` |
| Do metrics survive a restart? | Yes: every counter and latency sample is also written to PostgreSQL; p50/p95/p99, error rates, tokens and cost are queried per time window | [observability.md](docs/observability.md) |

The held-out and planted suites use scripted judge outputs, so they measure the **diagnosis engine**; judge quality is measured separately and depends on the model you configure. See [docs/diagnosis-benchmark.md](docs/diagnosis-benchmark.md) for the full framing.

## Architecture

![Retrace system architecture: console with session login and CLI drive a FastAPI backend with auth, rate limiting and request hardening; a six-stage diagnostic pipeline persists to PostgreSQL (traces plus durable telemetry) and ChromaDB, is measured by planted, held-out and calibration suites, experiments and a baseline regression gate, and feeds operations endpoints with p50/p95/p99 latency, cost and runbooks.](docs/assets/architecture.svg)

**How a request flows**

1. **Entry.** The React console signs in once with the API key and receives a short-lived HttpOnly session cookie; nothing secret ships in the bundle. The CLI calls the same service layer in-process with a Bearer key, so CI can run evaluations without the API. Every request passes the rate limiter, payload limit and security-header middleware and carries a `request_id`.
2. **Diagnostic pipeline.** A query is retrieved against a versioned corpus in ChromaDB (retrieved chunks are scanned for prompt-injection patterns), answered or abstained by an OpenAI-compatible LLM with bounded retries and per-execution cost, scored by three judges, then passed through the deterministic rule engine. The engine emits a `failure_code`, `rule_id`, raw score, **calibrated confidence**, an **uncertain** flag and a templated **explanation** built only from the observed signals.
3. **Investigation.** `GET /api/v1/investigations/{execution_id}` aggregates the execution, diagnosis, rule catalog entry, enriched retrieval chunks (`retrieved` / `expected` / `relevant` / `distractor` / `missing`), judge results, evidence rows and a latency timeline.
4. **Evaluation.** Suites run cases through the pipeline as experiments with per-class precision/recall/F1. A promoted experiment becomes the active baseline; later runs are gated with per-suite thresholds and exit `0`, `1` or `2`. `retrace benchmark report` adds calibration and the classifier comparison.
5. **Operations.** Structured, redacted logs feed an in-memory registry and a durable `metric_events` table. `GET /api/v1/metrics/durable` returns p50/p95/p99 latency, error rates, token usage and estimated cost for a window; signals link to runbooks.

Full details: [docs/architecture.md](docs/architecture.md), decisions in [docs/decisions.md](docs/decisions.md) (ADR-031 to ADR-043 cover v1.0).

## Features

| Area | What you get |
| --- | --- |
| Corpus and retrieval | Versioned ingest, chunking, `all-MiniLM-L6-v2` embeddings, Chroma top-k with traces, injection flags on chunks |
| Generation | OpenAI-compatible client with connect/read timeouts, retries on 429/5xx, token usage and `cost_usd` per execution |
| Judges | Relevance, faithfulness, contradiction; structured JSON, one retry, versioned prompts, validation tooling |
| Diagnosis | Ordered rules R00 to R90, failure taxonomy, `DIAGNOSIS_UNCERTAIN` outcome, calibrated confidence, evidence-based explanation |
| Investigation | One API and UI view of diagnosis, why, retrieval evidence, judges, timeline, runbooks, raw JSON |
| Evaluation | Planted (12), held-out (160), calibration (80) and gold suites with hash integrity; per-class metrics; selective-prediction metrics |
| Benchmarks | Classifier comparison (rules vs majority, heuristic, LLM), calibration report, retrieval ablation, judge validation, load test |
| Baselines and regression | Explicit promotion, per-suite thresholds, CI exit codes |
| Observability | Durable telemetry in PostgreSQL, p50/p95/p99, cost, signals, runbooks, liveness and readiness |
| Security | Session cookies, CSRF header, rate limits, payload limits, input validation, security headers, redaction |
| Console | Login, Investigate, Evaluations (per-class tables), Experiments, Operations (durable window) |

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend | FastAPI (Python 3.11), SQLAlchemy 2, Alembic, structlog, httpx |
| Database | PostgreSQL 16 (metadata, traces, experiments, durable telemetry) |
| Vector store | ChromaDB 0.5 |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` in-process; BM25 and hybrid retrievers in the ablation |
| LLM | Any OpenAI-compatible API; local Ollama recommended for development |
| Frontend | React 18, TypeScript, Vite, Vitest |
| Packaging | Docker Compose (Postgres, Chroma, backend, nginx-served frontend) |

## Quick start

### Prerequisites

- Docker Desktop (or a compatible Compose runtime)
- For local generation and judges: [Ollama](https://ollama.com) with a model such as `llama3.2:latest`

```bash
ollama pull llama3.2:latest
```

### 1. Configure

```bash
cp .env.example .env
# Set API_KEY (the operator credential). MODEL_* defaults target Ollama on the host.
```

Optional: set `SESSION_SECRET` to an independent random value; when unset it is derived from `API_KEY`.

### 2. Start

```bash
docker compose build
docker compose up -d
```

| Service | URL |
| --- | --- |
| Console | http://localhost:3000 (sign in with `API_KEY`) |
| API | http://localhost:8000 |
| Chroma | http://localhost:8001 |
| PostgreSQL | localhost:5432 |

Confirm migrations are at head:

```bash
docker compose exec backend alembic current
# expect: 007_telemetry_cost (head)
```

### 3. Seed the demo corpus

```bash
docker compose exec backend python /scripts/seed_demo_corpus.py   # or: make seed
```

The demo corpus is 13 internal-policy documents used by the retrieval ablation and the demo queries.

### Makefile shortcuts

| Target | Action |
| --- | --- |
| `make up` / `make down` | Build and start, or stop, all services |
| `make logs` | Follow backend logs |
| `make migrate` | Run Alembic migrations to head |
| `make seed` | Seed the demo corpus |
| `make eval` | Run an evaluation suite (`SUITE=planted_v1` by default) |
| `make test` | Run backend tests in the container |
| `make health` | Hit liveness and readiness endpoints |

## Using Retrace

Automation uses `Authorization: Bearer <API_KEY>`. The console uses a session cookie instead (`POST /api/v1/auth/session`) and must send `X-Requested-With: retrace-console` on writes.

```bash
export API_KEY=your_api_key_here
BASE=http://localhost:8000

curl -s $BASE/health/ready

# Run a query through the full RAG path and get an execution_id back
curl -s -X POST $BASE/api/v1/generate \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"corpus_version_id": "<corpus_version_id>", "query": "What is the refund window?"}'

# Diagnose that execution (returns failure_code, rule_id, calibrated_confidence, uncertain, explanation)
curl -s -X POST $BASE/api/v1/diagnose \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"execution_id": "<execution_id>"}'

# Full investigation view
curl -s $BASE/api/v1/investigations/<execution_id> -H "Authorization: Bearer $API_KEY"

# Durable metrics for the last hour
curl -s "$BASE/api/v1/metrics/durable?window_minutes=60" -H "Authorization: Bearer $API_KEY"
```

Key endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/auth/session`, `/api/v1/auth/logout`, `GET /api/v1/auth/me` | Console session login, logout, state |
| `POST` | `/api/v1/corpora`, `/api/v1/corpora/{id}/versions` | Create and ingest a corpus version |
| `POST` | `/api/v1/retrieve` | Retrieve top-k chunks with a trace and injection flags |
| `POST` | `/api/v1/generate` | Full RAG execution with tokens and cost |
| `POST` | `/api/v1/diagnose` | Run the rule engine on an execution |
| `GET` | `/api/v1/investigations/{execution_id}` | Aggregated investigation view |
| `POST` | `/api/v1/experiments` | Run a suite as an experiment |
| `GET` | `/api/v1/experiments/{id}/comparison` | Compare an experiment with the active baseline |
| `POST` | `/api/v1/baselines/promote` | Promote an experiment to the active baseline |
| `GET` | `/api/v1/metrics/durable`, `/metrics`, `/api/v1/signals`, `/api/v1/ops/summary` | Durable and in-memory metrics, signals, ops summary |
| `GET` | `/health/live`, `/health/ready` | Liveness; readiness (Postgres + Chroma) |

CLI (inside the backend container, `python -m app.cli.retrace ...`):

| Command | Purpose |
| --- | --- |
| `eval --suite heldout_v1` | Run a suite, persist the experiment, gate against the baseline, exit 0/1/2 |
| `baseline promote <experiment_id>` | Accept an experiment as the active baseline |
| `benchmark report --suite heldout_v1 --calibrate-on calib_v1 [--with-llm]` | Full benchmark: per-class metrics, calibration, classifier comparison, Markdown report |
| `retrieval-eval --corpus-dir /data/corpus/demo` | Chunking by retriever ablation with Recall@k, MRR, nDCG |
| `judges validate [--limit N]` | Judge accuracy, kappa, consistency and prompt sensitivity against labelled examples |

## Evaluation, benchmarks and regression gates

| Suite | Cases | Role |
| --- | ---: | --- |
| `planted_v1` | 12 | One unambiguous scenario per failure class; CI smoke gate (2% error ceiling) |
| `heldout_v1` | 160 | Generated from scenario semantics with 15% boundary cases; never used for tuning |
| `calib_v1` | 80 | Fits the confidence calibrator; disjoint from the held-out suite |
| `gold_v1` | 2 | Hand-written offline executions |

```bash
docker compose exec backend python -m app.cli.retrace eval --suite heldout_v1
docker compose exec backend python -m app.cli.retrace baseline promote <experiment_id>
docker compose exec backend python -m app.cli.retrace benchmark report \
  --suite heldout_v1 --calibrate-on calib_v1 --markdown /docs/benchmarks/heldout_v1.md --with-llm
python scripts/build_heldout_suite.py --check   # verify suite hashes
```

Held-out headline (full table and confusion matrix in [docs/benchmarks/heldout_v1.md](docs/benchmarks/heldout_v1.md)):

| Metric | Value |
| --- | --- |
| Lenient accuracy (predicted in acceptable codes) | 98.1% |
| Strict accuracy (exact label) | 93.1% |
| Macro-F1 / weighted-F1 | 0.947 / 0.940 |
| Deferred as uncertain | 1.9% (selective accuracy 100% at 98.1% coverage) |
| Calibration error, raw → calibrated | 0.128 → 0.004 (Brier 0.047 → 0.011) |
| Perfect per-class F1 | retrieval empty/miss, contradiction, hallucination, partial grounding, both abstention errors, timeout, malformed judge |
| Weakest classes | `RETRIEVAL_DISTRACTOR_DOMINANT` F1 0.69 and `OK_CORRECT_ABSTENTION` F1 0.77: the two are genuinely ambiguous at the 70% distractor threshold and the suite accepts either |

Exit codes are designed for CI: `0` pass, `1` regression against the baseline or below the suite's floors, `2` evaluation, integrity, config or runtime error. Thresholds are per suite (`backend/configs/thresholds.<suite>.yaml`).

## Retrieval quality

`retrace retrieval-eval` chunks the demo corpus with each configuration, embeds with the project's model, and scores dense cosine, Okapi BM25 and a reciprocal-rank-fusion hybrid against 87 hand-written queries (82 answerable, 5 unanswerable) whose relevance is defined independently of chunking. Headline rows from [docs/benchmarks/retrieval_ablation.md](docs/benchmarks/retrieval_ablation.md):

| Config | Retriever | Recall@5 | MRR | nDCG@10 |
| --- | --- | ---: | ---: | ---: |
| 512/64 (production) | dense, MiniLM | 0.947 | 0.849 | 0.869 |
| 512/64 | BM25 | 0.890 | 0.816 | 0.830 |
| 512/64 | dense, `bge-small-en-v1.5` | 0.972 | 0.889 | 0.905 |
| 1024/128 | hybrid RRF, `bge-small-en-v1.5` | 0.953 | 0.919 | 0.928 |

Takeaways: dense beats BM25 on paraphrased queries while BM25 matches it on literal ones; plain reciprocal-rank-fusion is not a free win (slightly worse than dense at 512/64, small gains at other sizes); larger chunks score higher partly for real reasons and partly because fewer chunks make hits easier; `bge-small` beats MiniLM consistently at the same size class, and `mpnet` does not. The embedding model stays pinned in production (ADR-004); the ablation is the evidence for changing it behind a new corpus version.

## Judge validation

`retrace judges validate` runs each judge against 66 author-labelled examples (24 relevance, 24 faithfulness, 18 contradiction, including partially supported answers, numerically wrong answers, missing-information-is-not-a-contradiction cases and chunks carrying prompt-injection text), reports accuracy, precision/recall/F1, Cohen's kappa and score error, checks inter-judge consistency (for example a contradiction verdict with a perfect faithfulness score), and measures how often labels flip across meaning-preserving prompt variants. Model, temperature, prompt version and prompt hash are recorded with every run.

Live result with a local `llama3.2` (3B, CPU, temperature 0, full 66-example set, zero schema failures across 282 calls):

| Judge | Agreement with labels | Note |
| --- | --- | --- |
| Contradiction | accuracy 0.89, kappa 0.78 (prompt `v1b`: 1.00) | handles missing-info and number-confusion cases; one false positive on the production prompt |
| Relevance | per-chunk accuracy 0.84, kappa 0.69; `context_sufficient` accuracy 0.29 | says "insufficient" for sufficient contexts; 13 to 20% of verdicts flip under prompt rewording |
| Faithfulness | kappa 0.02, score error 0.62 | returns a near-zero faithfulness score even for fully supported answers; not usable as a numeric signal with this model |

This is exactly why the diagnosis engine treats judge output as signals, cross-checks them (rule R90 flags self-inconsistent judge output as uncertain) and why the judge model must be validated before its verdicts are trusted. Method and full tables: [docs/benchmarks/judge_validation.md](docs/benchmarks/judge_validation.md), [docs/retrieval-and-judges.md](docs/retrieval-and-judges.md).

## Observability, cost and resilience

Every counter and latency sample is kept in a fast per-process view and written to a PostgreSQL `metric_events` table with one batched insert per request, so p50/p95/p99 latency, error rates, token usage and estimated cost survive restarts and are shared across uvicorn workers. `GET /api/v1/metrics/durable?window_minutes=` and `/api/v1/ops/summary` expose the durable window; `/api/v1/signals?source=durable` evaluates alert thresholds against it. Each execution trace stores `cost_usd` from a per-model pricing table (`backend/configs/pricing.yaml`, illustrative rates, local models cost 0). The LLM client uses a pooled HTTP client with separate connect and read timeouts and bounded exponential-backoff retries on transport errors and HTTP 429/5xx only, inside a total time budget, never on other 4xx or timeouts. Fault-injection tests cover LLM 5xx, 429 and timeouts, 20 concurrent generations, a Chroma outage (503 and `not_ready`) and database errors (500 `DATABASE_ERROR`). `scripts/load_test.py` measured 0% errors at concurrency 25 with retrieval saturating around 6 to 7 req/s on a single CPU-bound worker ([docs/benchmarks/load_test.md](docs/benchmarks/load_test.md)); `UVICORN_WORKERS` scales that out. There is no automatic pruning of `metric_events`; see [docs/observability.md](docs/observability.md) for retention SQL.

## Security

The console no longer ships a credential to the browser: the `VITE_API_KEY` build argument is gone, and the console asks for the operator API key once, exchanges it at `POST /api/v1/auth/session` for a short-lived HMAC-SHA256-signed HttpOnly cookie, and never keeps the key in the bundle, React state or local storage. The CLI, scripts and CI keep using `Authorization: Bearer <API_KEY>`; one dependency accepts either credential. Cookie-authenticated writes must carry `X-Requested-With: retrace-console`, which with `SameSite=Lax` and an explicit `CORS_ORIGINS` allow-list blocks cross-site request forgery (`403 CSRF_REJECTED`). A per-credential sliding-window rate limit (`RATE_LIMIT_PER_MINUTE`, with a tighter per-IP `AUTH_RATE_LIMIT_PER_MINUTE` on login) returns `429 RATE_LIMITED` with `Retry-After`. Bodies over `MAX_REQUEST_BYTES` are rejected with `413`, queries are stripped of control characters and capped at `MAX_QUERY_CHARS`, identifiers must match `^[A-Za-z0-9._-]+$`, and every response carries `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` and `Cache-Control: no-store`. Retrieved chunks are scanned by a conservative prompt-injection detector whose matches surface as `injection_flags`, a metric and a text-free log warning, while the generator prompt keeps all retrieved text inside `<retrieved_context>` in the user turn. Logs redact authorization headers, keys, tokens and passwords at any depth, and error envelopes never echo a presented credential. Not covered: multi-user accounts or RBAC, a key-rotation UI, server-side session revocation and distributed rate limiting. Threat model: [docs/security.md](docs/security.md).

## Tests

```bash
# Backend (inside the container)
docker compose exec backend pytest -v

# Backend against the working tree, no rebuild (Postgres + Chroma must be up)
scripts/dev_test.sh
scripts/dev_test.sh tests/test_security.py -k csrf

# Frontend (on the host)
cd frontend && npm install && npm test && npm run build
```

Every push and pull request runs [CI](.github/workflows/ci.yml): ruff, suite-hash integrity, the backend suite inside the Docker image against real Postgres and Chroma, and frontend type-check, tests and build. At v1.0.0: 217 backend tests (about 100 seconds against the Compose stack) and 11 frontend tests. Backend coverage by area: infrastructure, corpus and retrieval, generation, diagnosis, evaluation suites, experiments and baselines, observability, investigation, security (51 tests), durable telemetry (17), resilience and fault injection (18), retrieval metrics, judge validation, and the held-out benchmark, which runs all 160 cases and fails below the documented floors.

## Repository structure

```text
retrace/
├── backend/
│   ├── app/
│   │   ├── api/            # routers: auth, corpus, retrieve, generate, diagnose, investigate, experiments, benchmark, health
│   │   ├── cli/            # retrace CLI: eval, baseline, benchmark report, retrieval-eval, judges validate
│   │   ├── core/           # config, security, ratelimit, hardening, injection, logging, redaction, metrics, telemetry, signals
│   │   ├── db/             # SQLAlchemy models and session
│   │   ├── schemas/        # Pydantic request/response models
│   │   └── services/       # ingestion, retrieval, generation, pricing, judges/, diagnosis/, eval/, metrics/, retrieval_eval
│   ├── alembic/            # Migrations 001 to 007
│   ├── configs/            # thresholds per suite, calibration.json, pricing.yaml, observability signals
│   ├── datasets/           # suites (planted, heldout, calib, gold), retrieval qrels, judge labels
│   └── tests/
├── frontend/               # React + Vite console
├── scripts/                # seed, demo, build_heldout_suite, load_test, dev_test.sh, validation helpers
├── docs/
│   ├── benchmarks/         # heldout_v1, retrieval_ablation, judge_validation, load_test
│   ├── assets/             # architecture diagram
│   ├── runbooks/
│   └── architecture, security, observability, diagnosis-benchmark, retrieval-and-judges, decisions, demo, development, release
├── data/corpus/demo/       # 13 demo policy documents
├── docker-compose.yml · Makefile · .env.example · CHANGELOG.md · LICENSE
```

## Configuration

Copy [`.env.example`](.env.example) to `.env`. The important groups:

| Variable | Purpose |
| --- | --- |
| `API_KEY` | Operator credential for Bearer calls and console login |
| `SESSION_SECRET`, `SESSION_TTL_MINUTES`, `COOKIE_SECURE` | Session cookie signing key, lifetime, Secure flag |
| `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `MAX_QUERY_CHARS`, `MAX_REQUEST_BYTES` | Abuse controls |
| `DATABASE_URL`, `POSTGRES_*`, `CHROMA_HOST`, `CHROMA_PORT` | Stores (Compose wires these) |
| `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`, `MODEL_TIMEOUT_SECONDS`, `MODEL_MAX_RETRIES`, `MODEL_CONNECT_TIMEOUT_SECONDS` | OpenAI-compatible LLM endpoint and resilience |
| `EMBEDDING_MODEL` | Locked to `sentence-transformers/all-MiniLM-L6-v2` |
| `TELEMETRY_DURABLE`, `PRICING_PATH`, `UVICORN_WORKERS` | Durable metrics, cost table, worker count |
| `CORS_ORIGINS`, `LOG_LEVEL`, `ENVIRONMENT` | Console origins, logging, environment |

## Known limitations

- Held-out and planted suites use synthetic fixtures with scripted judge outputs; they measure the diagnosis engine, not live-LLM robustness. Judge quality must be re-measured for your model.
- The LLM classifier comparison and judge validation were run with a local 3B model; stronger models will score differently.
- The load test ran on one developer machine with a single uvicorn worker; it is a baseline, not a capacity claim.
- Single operator identity: no RBAC, key rotation UI or server-side session revocation. Rate limits are per process.
- No automatic pruning of durable telemetry; no Kubernetes, Datadog, Langfuse, Prometheus server, agents or auto-remediation.

## Documentation

- [Architecture](docs/architecture.md) · [Design decisions](docs/decisions.md) · [Changelog](CHANGELOG.md)
- [Diagnosis benchmark method](docs/diagnosis-benchmark.md) · [Retrieval and judge method](docs/retrieval-and-judges.md)
- [Security](docs/security.md) · [Observability](docs/observability.md)
- [Benchmarks](docs/benchmarks/): [held-out](docs/benchmarks/heldout_v1.md), [retrieval ablation](docs/benchmarks/retrieval_ablation.md), [judge validation](docs/benchmarks/judge_validation.md), [load test](docs/benchmarks/load_test.md)
- [Development](docs/development.md) · [Demo walkthrough](docs/demo.md) · [Release](docs/release.md) · [Runbooks](docs/runbooks/README.md)

## License

MIT. See [LICENSE](LICENSE).
