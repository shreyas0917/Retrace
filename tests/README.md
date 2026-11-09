# Tests

All automated tests live in `backend/tests/` (pytest) and `frontend/src/test/` (vitest).

```bash
# Backend, inside the running stack
docker compose exec backend pytest -v

# Backend, against the working tree without rebuilding the image
docker compose up -d postgres chroma
scripts/dev_test.sh                              # whole suite
scripts/dev_test.sh tests/test_security.py -k csrf

# Frontend (host)
cd frontend && npm install && npm test && npm run build
```

Test files are named by what they test:

| File | Covers |
| --- | --- |
| `test_infrastructure.py` | settings, health, auth basics (T01 to T10) |
| `test_corpus_retrieval.py` | corpus, chunking, embedding, retrieval |
| `test_generation.py` | generation, RAG execution, abstention, traces |
| `test_diagnosis_rules.py` | diagnosis rules, judges, taxonomy |
| `test_eval_suites.py` | gold and planted suites, benchmark metrics |
| `test_experiments_baselines.py` | experiments, baselines, `retrace eval` |
| `test_observability.py` | metrics, signals, redaction, health |
| `test_investigation_api.py`, `test_investigation_correctness.py` | investigation API and runbooks |
| `test_security.py` | auth, CSRF, rate and size limits |
| `test_telemetry.py`, `test_telemetry_retention.py` | durable telemetry, cost, retention |
| `test_resilience.py` | retries, timeouts, fault injection |
| `test_retrieval_metrics.py` | retrieval metrics and ablation |
| `test_judge_validation.py`, `test_label_review_sheet.py` | judge validation and label review |
| `test_faithfulness_nli.py` | NLI faithfulness judge |
| `test_external_traces.py` | bring-your-own-trace API and CLI |
| `test_live_suite.py`, `test_live_labels.py` | live_v1 recording, labelling merge and report |
| `test_benchmark_calibration_write.py` | calibration is written only on request |
| `test_v1_diagnosis_benchmark.py` | held-out diagnosis benchmark floors |
| `test_concepts_doc.py` | `docs/concepts.md` rule table matches the rule catalog |
