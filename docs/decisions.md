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

Status: Superseded by the v1.0 records below (the project continued past the Phase 9 scope).

---

# Architecture Decision Records (v1.0)

## ADR-031 — Explicit uncertain outcome (`DIAGNOSIS_UNCERTAIN`, rule R90)

Decision: When judges ran but their outputs are self-inconsistent (faithfulness below threshold with zero unsupported claims, or a required verdict missing), the engine returns `DIAGNOSIS_UNCERTAIN` with recommendation `MANUAL_REVIEW` instead of falling through to `EVAL_INTERNAL_ERROR`. Any decision whose calibrated confidence is below `TAU_UNCERTAIN` (0.5) is additionally flagged `uncertain` / `review_recommended` while keeping its primary code.

Reason: Ambiguous or conflicting judge signals were previously reported as infrastructure errors, which hid the real cause and inflated confidence. Reviewers asked for an abstain option; keeping the primary code keeps metrics comparable and lets the benchmark report selective accuracy versus coverage.

Status: Accepted

---

## ADR-032 — Templated, evidence-based explanations

Decision: Every diagnosis stores an `explanation` string assembled from the signal bag and the matched rule (`app/services/diagnosis/explain.py`). No LLM is involved.

Reason: The explanation must be reproducible from stored signals and must never assert anything the engine did not observe. It is shown in the Investigate view and in benchmark reports for misclassified cases.

Status: Accepted

---

## ADR-033 — Histogram-binned confidence calibration

Decision: `diagnosis_score` stays a heuristic rule strength (ADR-019), but a calibrator fitted on `calib_v1` maps it to empirical accuracy; the result is persisted as `calibrated_confidence` with `calibration_version`. The table lives in `backend/configs/calibration.json`; empty bins fall back to the raw score.

Reason: Reviewers asked for calibrated confidence. Histogram binning is transparent, needs no dependencies, and its expected calibration error and Brier score are reported before and after on the held-out suite.

Status: Accepted

---

## ADR-034 — Generated held-out and calibration suites

Decision: `scripts/build_heldout_suite.py` deterministically generates `heldout_v1` (160 cases) and `calib_v1` (80 cases) from scenario templates whose labels derive from scenario semantics, with about 15% boundary cases. Suites are hash-pinned and never used to tune rules or thresholds. The generator is committed so the suites can be regenerated and audited.

Reason: Twelve planted scenarios cannot estimate per-class precision/recall or calibration. Human-labelled live traces do not exist yet for this project; a seeded generator is the honest, reproducible alternative and is documented as synthetic.

Status: Accepted

---

## ADR-035 — Per-suite acceptance thresholds

Decision: `load_thresholds(suite_id=...)` picks `configs/thresholds.<suite_id>.yaml` when present. The held-out suite uses absolute floors (accuracy >= 0.80) and a 20% error-rate ceiling instead of the planted suite's 2%.

Reason: The planted suite is expected to be perfect; a boundary-heavy held-out suite is not. One global error-rate ceiling made every held-out run a "regression".

Status: Accepted

---

## ADR-036 — Rule engine remains the reference; alternatives are benchmarked, not deployed

Decision: `app/services/diagnosis/classifiers.py` adds majority, heuristic and LLM classifiers that consume the same `SignalBag`. `retrace benchmark report` compares them on identical persisted signals and reports Cohen's kappa. Production diagnosis still uses the rule engine only.

Reason: Reviewers asked how the rules compare to an LLM classifier and a trivial baseline. Running the comparison on stored signals guarantees identical inputs and keeps the production path deterministic.

Status: Accepted

---

## ADR-037 — Session cookie auth for the console; Bearer for automation

Decision: The frontend no longer receives the API key at build time. It exchanges the key once at `POST /api/v1/auth/session` for a short-lived HMAC-signed `HttpOnly` cookie; cookie-authenticated writes require `X-Requested-With: retrace-console`. `require_auth` accepts either the cookie or `Authorization: Bearer`. Supersedes the frontend half of ADR-003.

Reason: A key embedded in a browser bundle is not a secret. Stateless signed sessions need no new table and keep CLI/CI unchanged.

Status: Accepted

---

## ADR-038 — Rate limiting, payload limits and input validation at the edge

Decision: Pure-ASGI middleware enforces a per-credential sliding-window limit (`RATE_LIMIT_PER_MINUTE`, stricter on the login endpoint), rejects bodies above `MAX_REQUEST_BYTES`, adds security headers, and schemas cap query length and strip control characters. Retrieved chunks are scanned for prompt-injection patterns and flagged, never rewritten.

Reason: Minimal abuse controls that do not require external infrastructure; flags are evidence for the engineer, not automatic filtering that could hide failures.

Status: Accepted

---

## ADR-039 — Durable telemetry in PostgreSQL alongside in-memory metrics

Decision: Counters and latency observations are buffered and flushed to a `metric_events` table (migration 007); `/api/v1/metrics/durable` aggregates p50/p95/p99, error rates, token usage and estimated cost over a time window. The in-memory registry stays as the fast path. Supersedes the "not durable" limitation in ADR-026.

Reason: Metrics that vanish on restart cannot support incident review or trend reporting. PostgreSQL is already a dependency; no Prometheus server is introduced.

Status: Accepted

---

## ADR-040 — Cost per execution from a pricing table

Decision: `ExecutionTrace` gains `cost_usd` and `pricing_version`, computed from `configs/pricing.yaml` (USD per million tokens; local models cost 0). Unknown models yield null, never a guess.

Reason: Reviewers asked for token usage and cost per execution; a versioned pricing file keeps the estimate auditable.

Status: Accepted

---

## ADR-041 — LLM client retries only on transient failures

Decision: `OpenAICompatibleProvider` retries HTTP 429/5xx and transport errors with exponential backoff and jitter (`MODEL_MAX_RETRIES`), separates connect and read timeouts, and never retries other 4xx responses or exceeds the overall timeout budget.

Reason: Resilience without masking genuine request errors; timeouts must still surface as `GENERATION_TIMEOUT` so the diagnosis taxonomy stays truthful.

Status: Accepted

---

## ADR-042 — Retrieval quality is measured, not assumed

Decision: `retrace retrieval-eval` computes Recall@k, MRR and nDCG against chunking-independent qrels (document id plus a must-contain substring) and compares chunking configurations, dense retrieval, BM25 and a reciprocal-rank-fusion hybrid on the same queries. Results live in `docs/benchmarks/retrieval_ablation.md`.

Reason: Using an embedding model and a vector store is not evidence of retrieval quality; the ablation gives numbers and a method to re-run them.

Status: Accepted

---

## ADR-043 — Judges are validated against labelled examples and prompt variants

Decision: `retrace judges validate` scores each judge against an author-labelled example set (accuracy, F1, Cohen's kappa, score MAE), checks inter-judge consistency, and measures label flip rate across meaning-preserving prompt variants, recording model, temperature, prompt version and prompt hash. Fixture-based numbers are always labelled as such.

Reason: Judge reliability bounds diagnosis reliability; it has to be measured per model and re-measured when prompts change.

Status: Accepted
