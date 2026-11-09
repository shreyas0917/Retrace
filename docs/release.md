# Release readiness (v1.1)

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
# expect: 008_external_traces (head)
```

## Automated validation

```bash
docker compose exec backend pytest -v
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/validate_release.py"
python scripts/build_heldout_suite.py --check
```

Frontend (host):

```bash
cd frontend && npm install && npm test && npm run build
```

## Benchmarks to regenerate before a release

| Report | Command |
| --- | --- |
| Held-out diagnosis benchmark, calibration, classifier comparison | `python -m app.cli.retrace benchmark report --suite heldout_v1 --calibrate-on calib_v1 --markdown /docs/benchmarks/heldout_v1.md [--with-llm]`; add `--write-calibration` only to refit the committed calibrator |
| Retrieval ablation | `python -m app.cli.retrace retrieval-eval --corpus-dir /data/corpus/demo --markdown /docs/benchmarks/retrieval_ablation.md` |
| Judge validation (live model, both faithfulness backends) | `python -m app.cli.retrace judges validate --faithfulness-backend both --markdown /docs/benchmarks/judge_validation.md --out /data/reports/judge_validation.json` |
| Live benchmark (`live_v1`, offline replay of recorded runs) | `python -m app.cli.retrace benchmark report --suite live_v1 --markdown /docs/benchmarks/live_v1.md --out /data/reports/live_v1_report.json` |
| Calibration check on real runs (never writes the calibrator) | `python -m app.cli.retrace benchmark calibration-cv --suite live_v1 --markdown /docs/benchmarks/calibration_live_v1.md --out /data/reports/calibration_live_v1.json`; `--suite heldout_v1 --distribution-only` for the held-out bin spread |
| NLI faithfulness latency (on an idle machine) | `scripts/dev_test.sh python /scripts/measure_nli_latency.py --out /docs/benchmarks/nli_latency.md` |
| Load test | `python scripts/load_test.py --endpoint retrieve --concurrency 25 --requests 300` |

All commands run inside the backend container (`docker compose exec backend ...`) or via `scripts/dev_test.sh`.

## Manual UI smoke

1. http://localhost:3000 loads and asks for the API key; signing in sets the session cookie.
2. Navigate Investigate / Evaluations / Experiments / Operations.
3. Load an `execution_id`; confirm failure code, rule, rule strength (with the observed live accuracy in its tooltip) and the "Why" explanation.
4. Import a trace → Load example → Send; the result opens on Investigate with the "External trace" badge.
5. Evaluations → `heldout_v1` → per-class table renders.
6. Operations → durable window shows p50/p95/p99 and cost; restart the backend and confirm the numbers persist.
7. Log out; confirm the API rejects console calls without the cookie.

## v1.1 release checklist

- [ ] **Claims audit:** every percentage, count, CI, kappa and latency in `README.md` and `docs/` (outside `docs/decisions.md`) resolves to a committed report under `docs/benchmarks/` that prints the command that produced it, and every provenance claim ("labelled by", "human", "reviewed") matches the dataset manifest (`annotator`, `human_reviewed`). Record the table in the release PR.
- [ ] Fresh clone: `make demo` succeeds, the printed deep link opens (HTTP 200), and `retrace diagnose --file` runs on all three `examples/traces/*.json`; record times and results.
- [ ] Security spot-check: `.env.example` has placeholders only; `/api/v1/traces` limits as in [security.md](security.md).
- [ ] All gates green: ruff format and check, mypy, `gen_concepts.py --check`, `build_heldout_suite.py --check`, backend tests, frontend tsc, tests and build.

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
| Suites | `backend/datasets/suites/` (planted_v1, gold_v1, calib_v1, heldout_v1, live_v1) |
| Example traces | `examples/traces/` |

## Explicit limitations

1. Held-out and planted suites use scripted judge outputs; they measure the diagnosis engine, not live-LLM robustness. `live_v1` measures the whole system on 50 real runs, with labels from an independent AI annotator not yet reviewed by a human.
2. Judge validation and the LLM classifier comparison depend on the configured model; numbers in the committed reports were produced with a local Ollama model and will differ for other models.
3. The load test ran on one developer machine with a single uvicorn worker; it is a baseline, not a capacity claim.
4. Single-operator authentication: one API key, one session identity. No RBAC, no key rotation UI, no server-side session revocation.
5. Rate limiting is per process; with multiple workers each process has its own budget.
6. No Kubernetes / cloud deployment / auto-remediation.

## Version

Application version: 1.1.0 (`backend/app/version.py`).
