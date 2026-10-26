# Development

## Clean-room

```bash
cp .env.example .env
docker compose down -v
docker compose build
docker compose up -d
docker compose exec backend alembic current      # expect 007_telemetry_cost (head)
docker compose exec backend pytest -v
```

Frontend (host):

```bash
cd frontend && npm install && npm test && npm run build
```

## Fast iteration on the backend

`scripts/dev_test.sh` runs commands inside the backend image with the working-tree source bind-mounted, so you do not rebuild the image for every change. Postgres and Chroma must be up.

```bash
docker compose up -d postgres chroma
scripts/dev_test.sh                                   # full pytest
scripts/dev_test.sh tests/test_security.py -k csrf    # one file / filter
scripts/dev_test.sh python -m app.cli.retrace eval --suite planted_v1
```

Environment overrides work through a shell: `scripts/dev_test.sh sh -c "MODEL_NAME=llama3.2:latest python -m app.cli.retrace judges validate --limit 10"`.

## UI

```bash
docker compose up --build -d
# UI http://localhost:3000  ·  API http://localhost:8000
```

The console signs in with the API key once (`POST /api/v1/auth/session`) and then uses an HttpOnly session cookie. For local Vite development (`npm run dev` on port 5173) keep `http://localhost:5173` in `CORS_ORIGINS`.

## Demo / seed

```bash
docker compose exec backend python /scripts/seed_demo_corpus.py
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/demo_generate_fake.py"
```

Full walkthrough: [demo.md](demo.md)

## CLI

```bash
python -m app.cli.retrace eval --suite heldout_v1
python -m app.cli.retrace baseline promote <experiment_id>
python -m app.cli.retrace benchmark report --suite heldout_v1 --calibrate-on calib_v1 --markdown /docs/benchmarks/heldout_v1.md
python -m app.cli.retrace retrieval-eval --corpus-dir /data/corpus/demo --markdown /docs/benchmarks/retrieval_ablation.md
python -m app.cli.retrace judges validate --markdown /docs/benchmarks/judge_validation.md
```

Regenerate the held-out and calibration suites (deterministic, stdlib only):

```bash
python scripts/build_heldout_suite.py          # writes backend/datasets/suites/{heldout_v1,calib_v1}
python scripts/build_heldout_suite.py --check  # verify manifests
```

## Observability

```bash
curl -s http://localhost:8000/health/live
curl -s http://localhost:8000/health/ready
curl -s http://localhost:8000/metrics
curl -s "http://localhost:8000/api/v1/metrics/durable?window_minutes=1440"
curl -s http://localhost:8000/api/v1/signals
curl -s http://localhost:8000/api/v1/ops/summary
curl -s http://localhost:8000/api/v1/runbooks
```

Design notes: [observability.md](observability.md). Load testing: `python scripts/load_test.py --help`.

## Security

Threat model, auth flows and limits: [security.md](security.md). Security tests: `backend/tests/test_security.py`.

## Migrations

```text
001 … → 006_phase6_experiments_baselines → 007_telemetry_cost
```

Schema changes go through Alembic only (ADR-002).

## Release

See [release.md](release.md).
