# Changelog

## Unreleased

### Console: rule strength instead of a calibrated percentage
- The Investigate verdict now shows **Rule strength: High/Medium/Low** rather than a "Calibrated confidence" percentage, because the committed calibrator is miscalibrated on real runs. The tooltip explains this and gives the observed live accuracy (highest strength ~95% correct, lowest ~6%, on a small AI-labelled, not-yet-human-reviewed sample), linking `docs/benchmarks/calibration_live_v1.md`.

### Calibration on real runs: observed accuracy, not a calibrated percentage (labels: independent AI annotator, not yet reviewed by a human)
- `retrace benchmark calibration-cv` measures the confidence score on the live runs, using the as-recorded diagnoses (ADR-047 exact matching) so its numbers match the `live_v1` headline. `docs/benchmarks/calibration_live_v1.md` now leads with an **observed-accuracy-by-rule-strength-level** table (raw 0.70 → 6.5% correct over 31 cases, raw 1.00 → 94.7% over 19, each with a Wilson 95% CI).
- The committed calibrator, fitted on the synthetic `calib_v1` suite, is **miscalibrated on real runs** (ECE 0.60 against the raw score's 0.41), so Retrace does not present a calibrated-confidence percentage on real runs. `calibration.json` is unchanged; nothing here writes it. A live-fitted calibrator would be a two-entry lookup table and is not adopted; refitting waits for a larger, human-reviewed live set with a held-out split (Future work).
- `docs/benchmarks/heldout_v1.md` warns that its calibrated confidence puts 153 of 160 cases in one bin, so its ECE is not meaningful evidence; `benchmark report` writes that warning itself when one bin holds 80% of the cases.

### Abstention sentinel parsing (ADR-047)
- The abstention sentinel is now matched tolerantly (case, whitespace, underscores or hyphens between the words, quotes and trailing punctuation): `INSUFFICIENT CONTEXT`, `insufficient_context` and `Insufficient context.` are abstentions. Before, only the exact `INSUFFICIENT_CONTEXT` counted, in the demo pipeline, the diagnosis engine and external-trace ingestion. Found during the `live_v1` evaluation, where all 8 unanswerable runs were missed this way.
- `exact_sentinel_matching()` brings back the old comparison for replaying earlier recordings as recorded.

### Judge validation (labels: AI-drafted, cross-checked by a second independent AI; not reviewed by a human)
- A second, fresh AI agent checked all 173 judge labels from the review sheet alone and suggested no changes (notes on 3 borderline rows). Applied with `judge_labels_review.py apply --annotator ai_draft_blind`: label values unchanged, annotator `ai_draft_blind`, manifest `human_reviewed: false`, new hash.
- `docs/benchmarks/judge_validation.md` regenerated with `judges validate --faithfulness-backend both`: the LLM and NLI faithfulness backends side by side, the label provenance read from the manifest, the exact command, and a Limits section.
- `judge_labels_review.py apply --annotator` takes `ai_draft_author_reviewed` (default, after the author's review) or `ai_draft_blind`.

### live_v1 benchmark (labelled blind by an independent AI annotator; not yet reviewed by a human)
- `live_v1` has labels, labelled blind by an independent AI annotator (fresh subagent, no access to Retrace predictions); not yet reviewed by a human. The annotator saw only the labelling sheet, the guide and the corpus chunks, and gave a reason and a high/low confidence per case (`data/labelling/live_v1_sheet.ai_draft.csv`). The suite manifest records annotator `ai_draft_blind` and `human_reviewed: false`.
- `docs/benchmarks/live_v1.md` is generated from them by `retrace benchmark report --suite live_v1` and states that provenance at the top. Human review is planned (v1.1.1).
- `live_labelling.py merge --annotator` takes `author`, `ai_draft_blind` or `ai_draft_author_reviewed`. The reviewed mode needs `--draft`, refuses rows without an agree/change decision, and records how many cases the review changed; the report then says "AI-drafted, reviewed and corrected by the author (N of 50 changed)".
- `scripts/build_review_page.py` builds `data/labelling/REVIEW_ME.html` (not committed): one case per screen, low-confidence cases first, Agree/Change, CSV export. It reads only blind inputs, so it cannot show a prediction or an injected condition.
- The live report labels every miss cause as "suggested" and has a "What this does and doesn't show" section. Reports run through `scripts/dev_test.sh` now name their commit (`RETRACE_GIT_COMMIT`).
- The report's headline is the diagnosis Retrace made with the code that recorded the runs (the sentinel matched exactly then). A secondary row re-diagnoses the same recordings with the ADR-047 fix: it recognises the 8 abstentions but the rules then call them `RETRIEVAL_DISTRACTOR_DOMINANT` rather than the labelled `OK_CORRECT_ABSTENTION`, so accuracy is unchanged — a second rule/label disagreement for human review, not an improvement.
### Docs and onboarding (Phase 5)
- README rewritten: what Retrace does, a worked example from real `retrace diagnose` output, a `make demo` quickstart, using it on your own RAG app, and a results table whose live_v1 headline is pending the author's labels. Endpoint, CLI and configuration tables moved to `docs/reference.md`; security, observability and benchmark detail stays in `docs/`. The held-out suite is described as an engine logic test on synthetic signals, and the held-out accuracy badge is gone.
- `docs/concepts.md`: a plain-English glossary and the rule table, generated from `rule_catalog.py` by `scripts/gen_concepts.py` and checked in CI and by `tests/test_concepts_doc.py`.
- `make demo`: creates `.env` with a generated `API_KEY` if missing, starts the stack, waits for readiness, seeds the demo corpus, posts an example trace and prints the console URL and an Investigate deep link. Needs no LLM: without a reachable model it posts the retrieval-miss example, which the rules decide from gold chunk ids alone.
- References to the unpublished requirements document are gone, and the phase-numbered tests and scripts are named by what they test (`validate_phase9.py` is now `validate_release.py`); CI fails if either comes back.
- Scripts no longer fall back to a hard-coded API key; they read `API_KEY` from the environment or `.env` and otherwise exit with a clear message. Fixed the demo corpus count in `docs/demo.md` (13 documents) and the migration head in the development and release docs (008).

### Console redesign (Phase 7)
- Merged the parked `console-refresh` branch (light/dark/system theme, Overview page, plain-English diagnosis) and removed `framer-motion`: view and list fades are CSS transitions, and `prefers-reduced-motion` turns them off. No UI library was added.
- `frontend/src/labels.ts` replaces `taxonomy.ts` and holds the human labels for every failure code in `taxonomy.py` (including reserved codes), recommendation codes, diagnosis and operations signals, evaluation metrics, suites, judges and statuses. A test parses the backend files and fails if a code has no label. Raw codes are still shown, next to their label.
- Investigate: the verdict comes first (plain-English title with the failure code, rule and calibrated confidence), followed by a Retrieval, Context, Answer, Abstention stage strip. The strip marks the stage that broke, shows later stages as not assessed because rules are first-match, and shows every stage as unknown for `EVAL_*` codes. Then come a next-step card built from `recommendation_code` with the runbook rendered inline from Markdown, the model answer beside the best evidence chunk, a chunk table with similarity bars and expandable text, judge cards with readable fields (NLI faithfulness shows each claim, its best chunk, entailment, support and the truncation flag), how the rule decided (matched conditions, signals with tooltips, evidence references that scroll to and highlight the chunk), a latency waterfall, collapsible execution details and the raw JSON. A sticky jump-nav links the sections. External traces show an "External trace" badge and no empty corpus fields.
- The Investigate empty state has example questions and a four-step "How it works" panel.
- New "Import a trace" tab: paste JSON, get client-side checks for obvious mistakes (invalid JSON, missing `query`, `answer` or `retrieved_chunks`, a chunk without `chunk_id` or `text`), send it to `POST /api/v1/traces`, and open the result. API validation errors are listed per field. "Load example" fills in `examples/traces/contradiction.json` (bundled as `frontend/src/examples/contradictionTrace.json`; a test keeps the two identical).
- Deep links: `?execution=<id>` opens Investigate on that execution, also after signing in, and the URL follows the open execution (back and forward work).
- Evaluations and Experiments: a pass, regression or error banner with the exit code (for stored runs it is derived from the stored comparison the same way the gate computes it), six metric tiles with help tooltips, per-class F1 bars sorted weakest first with a callout for classes below 0.9, a failures-first case table with search and "Investigate →" links, baseline deltas as signed percentage points (F1 as decimals), and run identifiers under "Run details". `live_v1` is in the suite picker; choosing a suite never starts a run.
- Operations: a health verdict banner, alerting signals first, bars showing actual against threshold, and runbooks rendered inline from Markdown. The Overview request-error colour now follows the `request_error_rate` signal instead of a fixed 2% cut-off.
- Accessibility: a skip link, visible focus outlines, keyboard-operable tabs, focusable tooltips, labelled tables and regions. Wide tables scroll inside their own container, so pages do not scroll sideways at 390 px.
- `docs/assets/console-investigate.png` shows the Investigate page for `examples/traces/contradiction.json`, using the diagnosis from a local run of that example.
- Frontend tests go from 12 on main (22 after the merge) to 68 (stage logic, labels against the backend, the import form, deep links, the case filter, comparison formatting, the investigation report). The backend is unchanged.

### Lint, types and telemetry retention (Phase 6)
- The code base is formatted with `ruff format`, and lint now selects E9, F, I, B and UP (import order, bugbear, pyupgrade). Migrations are excluded so they stay frozen. CI checks formatting.
- `mypy` checks `app/services/diagnosis` and `app/services/eval` with `disallow_untyped_defs` (config in `backend/mypy.ini`), as a new CI job. The faithfulness router now returns the union of its two result types instead of `BaseModel`.
- Telemetry retention: `TELEMETRY_RETENTION_DAYS` (default 14) and `retrace telemetry prune [--days N] [--dry-run] [--batch-size N]`, which deletes old `metric_events` rows in batches of 5,000. `TELEMETRY_PRUNE_ENABLED=true` runs the prune daily in the API, guarded by a Postgres advisory lock so only one worker prunes per round. See `docs/observability.md`.
- Fixed a closure in the retrieval ablation that read the BM25 index through the loop variable rather than binding it (B023); results are unchanged because each closure ran within its own iteration.

### NLI pair cap
- The default `NLI_MAX_PAIRS` is now 500 (was 2000). At the measured CPU rate that bounds one answer at roughly 16 s instead of about a minute; the recorded live runs used 51 to 146 pairs, so normal answers are not truncated. Still configurable (minimum 20).

### Live benchmark, recording and blind labelling (Phase 3)
- `scripts/build_live_suite.py` records about 50 real pipeline runs for `live_v1` (real retrieval, generation and judges) and appends each run record to `runs.jsonl` as soon as it finishes, so an interrupted build resumes where it stopped. `--verify-replay` checks that offline replay reproduces every live diagnosis; `--freeze` writes `runs_manifest.json`, which `build_heldout_suite.py --check` now verifies (ADR-046).
- Eval-only generator faults (`wrong_facts`, `extra_unsupported_claim`) through `run_rag(eval_fault=...)`; the public `POST /api/v1/generate` cannot set them. Corpus variants without four documents, or with six near-topic documents, are ingested as separate corpora and never change `demo`.
- Offline fixtures accept a recorded NLI result and record the real generation model and prompt version; the suite runner uses them instead of fixed placeholders when present.
- `scripts/live_labelling.py merge` (run in the backend image) reads the labelled sheet back, validates every row at once (codes, gold chunk or document ids, yes/no fields, missing or edited rows), and writes `cases.jsonl` and `manifest.json` with the recorded runs as offline executions and the injected condition as a tag. `--dry-run` validates without writing; an existing `cases.jsonl` is replaced only with `--force`.
- `retrace benchmark report --suite live_v1` evaluates the labelled suite offline and writes lenient and strict accuracy and macro-F1 with bootstrap 95% CIs, per-class precision, recall and F1 with supports, the confusion matrix, the deferral rate, a breakdown per injected condition, and one error-analysis line per miss. The cause in each line is an automatic first pass comparing judge signals with the label, marked for review.
- `scripts/live_labelling.py export` writes a blind labelling sheet (CSV plus a read-only HTML view and the corpus chunk list) with no condition, judge output or prediction on it. `docs/labelling-guide.md` explains the codes, the decision order and three worked examples. No labels are written by the tooling.

### Claim-level NLI faithfulness (Phase 2)
- Faithfulness now defaults to a claim-level NLI judge (`FAITHFULNESS_BACKEND=nli`, ADR-045): a deterministic claim splitter, `cross-encoder/nli-deberta-v3-small` pinned to a commit and pre-downloaded in the image, premises cut into single sentences and adjacent sentence pairs (SummaC-style; whole-paragraph premises made the model call verbatim support neutral), overlapping windows for over-long sentences, and one batched scoring call. The label order is read from the model config. A claim is supported when entailment is its top label for some premise unit, and contradicted only if no unit supports it; nothing was tuned on labels.
- Results keep the rules' schema (`faithfulness_score`, claims) and add per-claim evidence, the pinned model and revision, and an `nli_contradiction` cross-check signal that no rule reads yet. The LLM judge remains available with `FAITHFULNESS_BACKEND=llm`.
- Replay rule: suites with recorded judge outputs replay them whatever the backend; recorded NLI results (`faithfulness_nli`) replay too, for `live_v1`.
- `retrace judges validate --faithfulness-backend llm|nli|both` (default `both`) adds claim-level, answer-level and contradiction-flag metrics for NLI, plus a threshold sensitivity table with grouped cross-validation. No new numbers are published until the label review is applied.
- `NLI_MAX_PAIRS` (default 500, minimum 20) caps the claim and premise pairs scored per answer. Chunks are scored from the highest retrieval similarity down; when the cap stops scoring early the result records `truncated: true`, `max_pairs`, `chunks_total` and `chunks_skipped`.
- `scripts/measure_nli_latency.py` writes `docs/benchmarks/nli_latency.md`: claims, pairs scored and CPU milliseconds for the three example traces and for one synthetic answer at the cap.
- The Docker image now installs `torch==2.14.1` and every other package against `backend/constraints.txt`: the exact 116 versions from the image the published benchmarks ran in. Before this, a rebuild pulled newer unpinned versions (for example torch 2.15 and python-dateutil 4).

### Bring your own trace (Phase 1)
- `POST /api/v1/traces` stores a trace produced by any RAG app and diagnoses it with the same engine; `diagnose: false` stores it only. `POST /api/v1/traces/batch` takes a JSON array or JSON Lines (up to `MAX_TRACE_BATCH`) and returns one result per trace, so one bad trace never fails the batch. The default cap is 25; larger batches should use the CLI.
- The caller's chunk texts are what the judges read; Retrace's corpus and vector store are never consulted. Responses include `injection_flags`, `abstention_detected_by` and `warnings` (for example, no `gold_chunk_ids` means retrieval-miss detection is unavailable).
- `retrace diagnose --file/--batch [--fail-on CODES|ALL_FAILURES] [--json]` runs in process with exit codes 0, 1 and 2 for CI.
- Migration `008_external_traces`: `execution_traces.source` (`internal` or `external`), `trace_metadata`, and a nullable `corpus_version_id` that a check constraint keeps required for internal traces. Execution, diagnosis and investigation endpoints and the console handle the null corpus; investigations report `source: external`.
- Rule R02 (`EVAL_MISSING_CONTEXT`) now fires for any missing answer and skips the judges (ADR-044). No internal execution or suite case is affected.
- New settings `MAX_TRACE_CHUNKS`, `MAX_TRACE_CHUNK_CHARS`, `MAX_TRACE_ANSWER_CHARS`, `MAX_TRACE_BATCH`; docs in `docs/integrate.md`; sample inputs in `examples/traces/`.

### Calibration
- `retrace benchmark report` no longer rewrites `backend/configs/calibration.json` as a side effect. A fresh fit is reported for comparison; `--write-calibration` is required to write it, and the report states which calibrator its numbers used.

### Label provenance
- Corrected a false claim: the 66 judge labels and 87 retrieval queries were drafted by an AI agent, not written by hand. README and docs now say "AI-drafted, not yet reviewed", both datasets record `annotator: ai_draft`, and the generated reports carry a provenance note because their recorded hashes predate the metadata change.
- The same correction for the 12 `planted_v1` scenarios and the 2 `gold_v1` cases: they were AI-drafted, not hand-written. Their cases now record `annotator: ai_draft` (was `human_a`), the manifests carry a provenance line, and both suite hashes were recomputed (`planted_v1` sha256:94e67d46…, `gold_v1` sha256:102a431a…). Baselines promoted against the old hashes must be re-promoted.
- Removed an untrue "reviewed by the project author" line from the heldout suite generator.
- Added `scripts/judge_labels_review.py` and `data/labelling/judge_labels_v1_review.csv` (173 label rows) so the author can review every judge label before Phase 2 uses them. `apply` records the reviewer, date and number of changed labels.

## 1.0.0 — 2026-10-26

Addresses the seven gaps identified in the portfolio review: held-out benchmark, rule-engine comparison and calibration, retrieval quality evidence, judge validation, durable telemetry, security hardening, and scale/resilience evidence.

### Diagnosis
- New outcome `DIAGNOSIS_UNCERTAIN` (rule R90) for self-inconsistent or missing judge verdicts; `MANUAL_REVIEW` recommendation.
- Calibrated confidence via histogram binning fitted on `calib_v1`; `calibrated_confidence`, `calibration_version`, `uncertain` and `review_recommended` on every diagnosis.
- Templated, evidence-based `explanation` persisted with each diagnosis and shown in the console.
- Per-class precision / recall / F1, strict vs lenient accuracy, micro / weighted F1 and selective-prediction metrics stored with every experiment.
- Per-suite acceptance thresholds (`configs/thresholds.<suite>.yaml`).

### Benchmarks
- `heldout_v1` (160 cases) and `calib_v1` (80 cases) generated by `scripts/build_heldout_suite.py`; `retrace benchmark report` writes `docs/benchmarks/heldout_v1.md` with per-class metrics, confusion matrix, calibration (ECE, Brier, reliability bins) and a classifier comparison (rule engine vs majority, heuristic and LLM classifiers with Cohen's kappa).
- `retrace retrieval-eval`: Recall@k, MRR, nDCG over chunking-independent qrels; chunking grid, dense vs BM25 vs hybrid; report in `docs/benchmarks/retrieval_ablation.md`. Demo corpus expanded to 12 documents.
- `retrace judges validate`: judge accuracy, F1, Cohen's kappa and score MAE against labelled examples, inter-judge consistency and prompt-variant flip rate; report in `docs/benchmarks/judge_validation.md`.
- `scripts/load_test.py` with results in `docs/benchmarks/load_test.md`; fault-injection tests for LLM timeouts and errors, Chroma and database failures, concurrent executions.

### Security
- Console authenticates with a short-lived HMAC-signed HttpOnly session cookie (`/api/v1/auth/*`); the `VITE_API_KEY` build argument is removed. Bearer keys remain for CLI and automation.
- CSRF header requirement for cookie-authenticated writes, per-credential rate limiting (429 with Retry-After), payload size limit (413), security headers, query length and control-character validation, identifier patterns.
- Prompt-injection detector flags retrieved chunks (`injection_flags`, `retrieval.injection_suspected`).

### Observability and resilience
- Durable telemetry (`metric_events`, migration 007) with p50/p95/p99 latency, error rates, token usage and estimated cost (`configs/pricing.yaml`); `GET /api/v1/metrics/durable`; Operations view shows the durable window.
- `cost_usd` and `pricing_version` on execution traces.
- LLM client: connect/read timeouts, bounded retries with backoff on 429/5xx and transport errors, retry metrics.
- `UVICORN_WORKERS` support.

### Developer experience
- `scripts/dev_test.sh` runs tests and CLI commands in the image against the working tree.
- Docs: security, observability, diagnosis benchmark method, retrieval and judge method, ADR-031 to ADR-043, refreshed demo, development and release guides, v1.0 architecture diagram.

## 0.9.0

Phases 1 to 9: corpus and retrieval, generation, judges, deterministic diagnosis, planted and gold suites, experiments and baselines, in-memory observability, investigation UI, release validation.
