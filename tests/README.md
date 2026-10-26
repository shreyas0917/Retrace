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

Test files map to subsystems: infrastructure (T01 to T10), corpus and retrieval, generation,
diagnosis, evaluation suites, experiments and baselines, observability, investigation,
plus the v1.0 additions: security (`test_security.py`), durable telemetry
(`test_telemetry.py`), resilience and fault injection (`test_resilience.py`),
retrieval metrics (`test_retrieval_metrics.py`), judge validation
(`test_judge_validation.py`) and the held-out diagnosis benchmark
(`test_v1_diagnosis_benchmark.py`).
