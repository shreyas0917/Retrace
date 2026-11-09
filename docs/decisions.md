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

Decision: `retrace judges validate` scores each judge against an example set (AI-drafted, not yet reviewed) (accuracy, F1, Cohen's kappa, score MAE), checks inter-judge consistency, and measures label flip rate across meaning-preserving prompt variants, recording model, temperature, prompt version and prompt hash. Fixture-based numbers are always labelled as such.

Reason: Judge reliability bounds diagnosis reliability; it has to be measured per model and re-measured when prompts change.

Status: Accepted

---

## ADR-044 — Bring-your-own-trace, and R02 for any missing answer

Decision: `POST /api/v1/traces`, `POST /api/v1/traces/batch` and `retrace diagnose` accept traces produced by any RAG app. They are stored as `ExecutionTrace` rows with `source = 'external'`; migration 008 makes `corpus_version_id` nullable for them, with a check constraint that keeps it required for internal traces. The caller's chunk texts are stored on the trace and are what the judges read; Retrace's corpus and vector store are not consulted.

Rule R02 (`EVAL_MISSING_CONTEXT`) now fires whenever the answer is missing, and `needs_judges` skips the judges in that case. Before, R02 also required empty retrieval, so an answer-less trace with chunks ran the judges and could be reported as an answer-quality failure, for example `ABSTENTION_FALSE_NEGATIVE` ("answered when it should have declined") for an app that produced no answer at all.

Reason: external apps can legitimately send no answer, and diagnosing a non-existent answer is wrong. The change cannot affect internal executions or existing suites: the missing-answer signal excludes the `ABSTAINED`, `GENERATION_TIMEOUT` and `FAILED` statuses, which are the only ones the internal pipeline stores without an answer, and no suite case has a null answer with another status. The rule was not tuned on any benchmark.

Status: Accepted

---

## ADR-045 — Claim-level NLI faithfulness by default

Decision: The faithfulness judge defaults to a claim-level NLI backend (`FAITHFULNESS_BACKEND=nli`). The answer is split into claims by a deterministic sentence splitter; each claim is scored by `cross-encoder/nli-deberta-v3-small`, pinned to commit `fa2804872c3b4bd748f38c0185cc85775361e735` and pre-downloaded in the Docker image, against premise units cut from every retrieved chunk: each sentence and each adjacent pair of sentences. Whole chunks were the first design; a manual check showed the model scoring a verbatim supporting sentence as neutral inside a paragraph, so premises follow the SummaC approach instead. A unit longer than the model's token limit is split into overlapping windows, and all pairs are scored in one batched call. The label order is read from the model config, never assumed.

A claim is supported when entailment is the top NLI label for at least one premise unit, and flagged contradicted only when no unit supports it and some unit's top label is contradiction. These rules are fixed by design and was not tuned: the 24 labelled faithfulness examples are too few to choose a threshold from, and they are AI-drafted and not yet reviewed. Cross-validated thresholds are reported only as a sensitivity table. `faithfulness_score` is supported claims divided by claims, so the rules keep the schema they already read.

The NLI judge also reports `nli_contradiction` when any claim's top label is contradiction. It is stored as a cross-check signal; the LLM contradiction judge still decides rule R30.

Replay rule: suites whose cases carry recorded judge outputs replay them whatever the backend setting. Scripted LLM faithfulness replies replay through the LLM path, as before; a recorded NLI result (`faithfulness_nli`) replays as is. This keeps `heldout_v1`, `calib_v1`, `planted_v1` and `gold_v1` reproducible, and lets `live_v1` record real NLI outputs and re-diagnose them offline.

Rules: no rule changed. Because the score is derived from the claim list, the R90 branch for a low score with no unsupported claim cannot occur with this backend. An answer with no checkable claim gets a null score, which R90 reports as `DIAGNOSIS_UNCERTAIN` with `judge:faithfulness:missing`. The splitter falls back to the whole answer as one claim when every sentence is too short, so short factual answers are still checked.

Reason: the validation run showed the LLM faithfulness judge at near-zero agreement with the labels, returning low scores even for fully supported answers. That left rules R31, R33, R34 and R40 resting on a signal with no measured reliability. An entailment model checks each claim against the evidence directly, deterministically and without an LLM call.

Status: Accepted. Its accuracy against labels will be reported only after the author's label review.


---

## ADR-046 — live_v1: recorded real runs, labelled blind by the author

Decision: `live_v1` is built from about 50 real runs of the pipeline on the demo corpus: real retrieval, generation by the configured model at temperature 0, the configured LLM judges for relevance and contradiction, and the NLI faithfulness judge. Each query has an injected condition: clean, unanswerable, gold document removed, distractor documents added, a wrong-facts generator prompt, or an extra-unsupported-claim prompt.

How conditions are injected:

- Prompt faults are eval-only. `run_rag(eval_fault=...)` appends a fault instruction to the generator's system prompt and records `generator.v1+eval_fault.<kind>.<version>` as the prompt version. `GenerateRequest` has no such field and `POST /api/v1/generate` never passes one; a test posts the field and checks it is ignored.
- Corpus conditions are separate corpus versions under their own corpus ids (`demo_live_variant_a` without four documents, `demo_live_variant_b` with six near-topic documents added). The main `demo` corpus is never modified. Variants are defined in `corpus_variants.json` next to the queries.
- The condition is metadata, not the label. A wrong-facts prompt may still produce a correct answer; the author's label says what happened.

Recording: `scripts/build_live_suite.py` appends one run record per query to `runs.jsonl` as soon as it finishes and skips recorded queries on restart, so a long run can be interrupted. A record holds the query, corpus version and hash, the retrieved chunks with ranks and scores, the answer, every raw judge reply in call order (captured by wrapping the real provider), the persisted NLI result, the LLM faithfulness reply for comparison, model and prompt versions, the git commit, a timestamp and Retrace's live diagnosis. Diagnosis runs without gold ids, so every judge that could be needed is recorded. `--verify-replay` re-diagnoses each record offline from its recordings and must reproduce the live code and rule; `--freeze` writes `runs_manifest.json` with the hashes of the runs and the queries, which `build_heldout_suite.py --check` verifies.

Labelling: `scripts/live_labelling.py export` writes a blind sheet: query, ranked chunks and answer only, shuffled into sheet ids by a salted hash so the order says nothing about the condition. It never contains the condition, the fault, the corpus variant, any judge output or Retrace's prediction. The author labels it using `docs/labelling-guide.md`. No labels, including drafts, are written by the tooling. Only after the sheet comes back are labels merged into `cases.jsonl`, the hash recomputed and the benchmark run.

Reason: the headline numbers so far come from synthetic cases whose judge outputs were scripted from the same picture of failures as the rules. Real runs with blind human labels measure the whole system, judges included.

Status: Accepted. Recorded; awaiting labels.

## ADR-047 — Tolerant matching of the abstention sentinel

Context: the generator is told to reply exactly `INSUFFICIENT_CONTEXT` when the context does not answer the question. The demo pipeline (`rag.py`, which sets `abstained`), Retrace's diagnosis engine (which also checks the answer text) and external-trace ingestion all compared the answer with that string exactly. **This bug was found during the `live_v1` evaluation:** in all 8 `unanswerable` runs, `llama3.2` wrote `INSUFFICIENT CONTEXT` with a space, so every one was recorded as `abstained: false` and diagnosed `ABSTENTION_FALSE_NEGATIVE` (R20), although a reader sees a correct refusal.

Decision: `app/services/abstention.is_sentinel()` decides whether a whole answer is the sentinel, ignoring case, surrounding whitespace, quotes, backticks or bold markers, trailing punctuation, and any run of spaces, underscores or hyphens between the two words (or none). An answer that only contains the words inside a longer sentence is not the sentinel. `rag.py`, the engine's signal bag and `detect_abstention` all use it.

`exact_sentinel_matching()` restores the old exact comparison inside a `with` block. It exists only to replay recordings "as recorded": the `live_v1` headline stays the diagnosis Retrace made with the code that recorded the runs, and the fixed diagnosis of the same recordings is reported beside it as a secondary, optimistic number, not an independent measurement. No recording is redone.

Not changed here: the relevance judge's "context sufficient" weakness, the other main finding of `live_v1`; a change to it needs a separate validation set first.

Status: Accepted.
