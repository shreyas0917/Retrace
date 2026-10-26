# Release readiness (v1.0.0)

Checklist for presenting Retrace as a finished engineering project.

## Clean-room start

```bash
cp .env.example .env
docker compose down -v
docker compose build
docker compose up -d
```

Wait until the backend is healthy, then:

```bash
docker compose exec backend alembic current
# expect: 007_telemetry_cost (head)
```

## Automated validation

```bash
docker compose exec backend pytest -v
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/validate_phase9.py"
python scripts/build_heldout_suite.py --check
```

Frontend (host):

```bash
cd frontend && npm install && npm test && npm run build
```

## Benchmarks to regenerate before a release

| Report | Command |
| --- | --- |
| Held-out diagnosis benchmark, calibration, classifier comparison | `python -m app.cli.retrace benchmark report --suite heldout_v1 --calibrate-on calib_v1 --markdown /docs/benchmarks/heldout_v1.md [--with-llm]` |
| Retrieval ablation | `python -m app.cli.retrace retrieval-eval --corpus-dir /data/corpus/demo --markdown /docs/benchmarks/retrieval_ablation.md` |
| Judge validation (live model) | `python -m app.cli.retrace judges validate --markdown /docs/benchmarks/judge_validation.md` |
| Load test | `python scripts/load_test.py --endpoint retrieve --concurrency 25 --requests 300` |

All commands run inside the backend container (`docker compose exec backend ...`) or via `scripts/dev_test.sh`.

## Manual UI smoke

1. http://localhost:3000 loads and asks for the API key; signing in sets the session cookie.
2. Navigate Investigate / Evaluations / Experiments / Operations.
3. Load an `execution_id`; confirm failure code, rule, calibrated confidence and the "Why" explanation.
4. Evaluations → `heldout_v1` → per-class table renders.
5. Operations → durable window shows p50/p95/p99 and cost; restart the backend and confirm the numbers persist.
6. Log out; confirm the API rejects console calls without the cookie.

## Release artifacts

| Item | Location |
| ---- | -------- |
| Architecture | `docs/architecture.md`, `docs/assets/architecture.svg` |
| Security model | `docs/security.md` |
| Observability | `docs/observability.md` |
| Diagnosis benchmark method | `docs/diagnosis-benchmark.md` |
| Retrieval and judge method | `docs/retrieval-and-judges.md` |
| Benchmark reports | `docs/benchmarks/` |
| Development | `docs/development.md` |
| Demo script | `docs/demo.md` |
| Runbooks | `docs/runbooks/` |
| ADRs | `docs/decisions.md` |
| Demo corpus | `data/corpus/demo/` |
| Suites | `backend/datasets/suites/` (planted_v1, gold_v1, calib_v1, heldout_v1) |

## Explicit limitations

1. Held-out and planted suites use scripted judge outputs; they measure the diagnosis engine, not live-LLM robustness.
2. Judge validation and the LLM classifier comparison depend on the configured model; numbers in the committed reports were produced with a local Ollama model and will differ for other models.
3. The load test ran on one developer machine with a single uvicorn worker; it is a baseline, not a capacity claim.
4. Single-operator authentication: one API key, one session identity. No RBAC, no key rotation UI, no server-side session revocation.
5. Rate limiting is per process; with multiple workers each process has its own budget.
6. No Kubernetes / cloud deployment / auto-remediation.

## Version

Application version: 1.0.0.
