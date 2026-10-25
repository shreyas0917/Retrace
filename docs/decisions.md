# Architecture Decision Records (Phase 1)

## ADR-001 — PostgreSQL + Chroma

Decision: Use PostgreSQL for durable metadata and Chroma for vector storage.

Reason: Matches the locked Retrace Technical PRD (§8, §9). Chroma selected for Compose simplicity and persistent local collections.

Status: Accepted

---

## ADR-002 — Alembic migrations only

Decision: Schema changes go through Alembic. Do not use `Base.metadata.create_all()` as the deployment path.

Reason: Reproducible schema evolution across environments; PRD requirement.

Status: Accepted

---

## ADR-003 — Env API key for Phase 1 auth

Decision: Validate `Authorization: Bearer` against the `API_KEY` environment variable (constant-time compare). The `api_keys` table exists for later hashed multi-key support but is not required for Phase 1.

Reason: Smallest conventional solution that preserves the PRD Bearer contract without user accounts/OAuth/RBAC.

Status: Accepted

---

## ADR-004 — Embedding model pin

Decision: `EMBEDDING_MODEL` must equal `sentence-transformers/all-MiniLM-L6-v2`. Settings validation rejects substitutes.

Reason: PRD lock; prevents silent model drift that would invalidate reproducibility.

Status: Accepted

---

## ADR-005 — Chroma collection naming

Decision: `collection_name_for_corpus_version(id) -> "cv_{id}"`.

Reason: PRD: one Chroma collection per `corpus_version_id`.

Status: Accepted

---

## ADR-006 — Public health vs authenticated status

Decision: `/health` and `/api/v1/health` are unauthenticated liveness probes. `/api/v1/status` requires auth and checks Postgres + Chroma.

Reason: Orchestrators need an open liveness endpoint; dependency readiness should not be anonymously scrapable in a naive deployment.

Status: Accepted

---

## ADR-007 — No Redis/Kafka/Celery in Phase 1

Decision: Compose stack is backend, postgres, chroma, frontend only.

Reason: PRD and Step 6 scope forbid unnecessary brokers; async job queue is optional later when suite size demands it.

Status: Accepted

---

## ADR-008 — psycopg3 driver

Decision: Use `psycopg[binary]` v3 with SQLAlchemy URL scheme `postgresql+psycopg://`.

Reason: Current PyPI package named `psycopg` is v3; matches SQLAlchemy 2 recommended driver.

Status: Accepted

---

## ADR-009 — Corpus version status machine

Decision: Status values `CREATED | INGESTING | READY | FAILED`. Retrieval requires `READY`.

Reason: Step 7 / PRD immutability — never mark READY on partial failure.

Status: Accepted

---

## ADR-010 — Character-window chunking

Decision: MVP strategy `recursive_character` implemented as deterministic character windows (`chunk_size` / `chunk_overlap`). Chunk IDs: `{document_id}:c{ordinal:03d}`.

Reason: Smallest reproducible chunker matching PRD config fields; no tokenizer drift.

Status: Accepted

---

## ADR-011 — Embedding revision string

Decision: Store `embedding_revision` as `sentence-transformers/all-MiniLM-L6-v2@sentence-transformers-local`.

Reason: Local Docker install does not pin a HuggingFace commit SHA by default; string documents the local ST runtime for reproducibility of the demo stack.

Status: Accepted

---

## ADR-012 — Idempotent ingest

Decision: Identical `(corpus_id, corpus_hash, chunking_config_hash, embedding_model, embedding_revision)` returns the existing READY version. FAILED rows with the same identity are cleared and retried in place.

Reason: Prevents uncontrolled Chroma duplicates and unique-constraint dead-ends after failures.

Status: Accepted

---

## ADR-013 — OpenAI-compatible generation via httpx

Decision: Call `{MODEL_BASE_URL}/chat/completions` with httpx. Temperature fixed at `0`. Timeout from `MODEL_TIMEOUT_SECONDS`.

Reason: Smallest OpenAI-compatible client; no extra SDK; easy to fake in tests.

Status: Accepted

---

## ADR-014 — Forced abstention without LLM call

Decision: Empty/blank retrieval → `ABSTAINED` + `INSUFFICIENT_CONTEXT`, no provider call.

Reason: Matches PRD no-evidence behavior; prevents unnecessary hallucination risk before judges exist.

Status: Accepted

---

## ADR-015 — ExecutionTrace links RetrievalTrace

Decision: `execution_traces.retrieval_trace_id` FK + JSON snapshot of retrieved chunks.

Reason: Diagnosis later can reconstruct query → chunks → prompt → answer from one execution id.

Status: Accepted

---

## ADR-016 — Deterministic rules before judges

Decision: Diagnosis evaluates ordered rules R00–R40. Infrastructure / empty retrieval / gold miss short-circuit without calling judges. Relevance runs when needed; faithfulness and contradiction run only when context is judged sufficient and an answer was produced.

Reason: PRD: LLMs must not override deterministic failures; empty retrieval is not a semantic question.

Status: Accepted

---

## ADR-017 — Separate judges, structured JSON, one retry

Decision: Relevance, faithfulness, and contradiction are separate prompts. Output must validate against Pydantic schemas. Exactly one retry on malformed output, then `EVAL_JUDGE_MALFORMED` / R01. Temperature fixed at 0.

Reason: Judges supply signals; the rule engine owns diagnosis. No essay outputs, no ensembles.

Status: Accepted

---

## ADR-018 — One diagnosis per execution

Decision: Unique constraint on `diagnoses.execution_id`. Repeated `POST /api/v1/diagnose` returns the existing row without overwrite.

Reason: Preserve historical diagnostic evidence; Phase 4 does not yet model multi-attempt diagnosis runs.

Status: Accepted

---

## ADR-019 — Diagnosis confidence is rule strength

Decision: Confidence is only `high` | `medium` | `low`. Judge scores and future human-suite accuracy are separate concepts.

Reason: PRD §4 — do not present rule heuristics as calibrated probability.

Status: Accepted

---

## ADR-020 — Offline planted fixtures (no corpus mutation)

Decision: Planted-failure cases build ephemeral retrieve/answer snapshots and scripted judges. The READY demo Chroma collection is never deleted or rewritten during benchmark runs.

Reason: Reproducible injections without corrupting the canonical corpus; matches PRD offline diagnose mode.

Status: Accepted

---

## ADR-021 — Suite files under backend/datasets

Decision: Versioned suites live at `backend/datasets/suites/{suite_id}/v{semver}/` with `cases.jsonl` + `manifest.json` (PRD §5.3 layout).

Reason: Copied into the backend image; hash-verified on load; independent of gitignored `data/gold` placeholders.

Status: Accepted

---

## ADR-022 — Soft match via acceptable_primary_codes

Decision: A case scores correct when `predicted_primary ∈ acceptable_primary_codes`. `failure_label` is the intended primary under the designed fixture.

Reason: PRD §5.2 / §15 diagnosis_accuracy definition.

Status: Accepted

---

## ADR-023 — Explicit baseline promotion

Decision: Baselines are created only via `retrace baseline promote` / `POST /api/v1/baselines/promote`. Successful eval does not auto-promote.

Reason: PRD §16 — first green run is measured, then explicitly accepted.

Status: Accepted

---

## ADR-024 — Exit codes 0 / 1 / 2

Decision: `retrace eval` returns 0=pass, 1=regression (gate fail), 2=config/integrity/runtime error.

Reason: PRD §16; regressions are successful executions that miss thresholds, not infrastructure failures.

Status: Accepted

---

## ADR-025 — No-baseline eval still runs

Decision: Without an active baseline, eval still persists an experiment and applies absolute floors only. CLI prints promotion instructions. Default floors are 0.0 so a clean first run exits 0.

Reason: Allows measuring before accepting a baseline; promotion remains explicit.

Status: Accepted

---

## ADR-026 — In-memory metrics for local ops

Decision: Phase 7 metrics live in-process (`app.core.metrics`). Exposed via `GET /metrics`. Not durable; reset on restart.

Reason: PRD MVP observability without deploying a metrics backend.

Status: Accepted

---

## ADR-027 — Live vs ready health

Decision: `/health/live` = process alive; `/health/ready` = Postgres + Chroma. Optional services must not permanently fail liveness.

Reason: Standard probe split; preserves existing `/health` and `/api/v1/status`.

Status: Accepted

---

## ADR-028 — Log redaction processor

Decision: structlog pipeline includes `redact_event_dict` before JSON render. Sensitive keys (api_key, authorization, password, token, …) become `[REDACTED]`.

Reason: PRD §17/§18 — never log secrets.

Status: Accepted

---

## ADR-029 — Investigation aggregate API for Phase 8 UI

Decision: Expose `GET /api/v1/investigations/{execution_id}` that joins execution, diagnosis, judges, evidence, rule catalog, and timeline. Rule conditions come from a static catalog documenting `apply_rules` — the UI never re-implements diagnosis.

Reason: Engineers need one evidence view without raw DB inspection; avoid duplicating rule logic in React.

Status: Accepted

---

## ADR-030 — Phase 9 is validation/release only

Decision: Phase 9 adds no product features. Deliverables are clean-room validation (`scripts/validate_phase9.py`), demo/release docs, and version 0.9.0. No Phase 10.

Reason: Project scope ends at reproducible, demonstrable engineering completeness.

Status: Accepted
