# Development

## Clean-room (Phase 9)

```bash
cp .env.example .env
docker compose down -v
docker compose build
docker compose up -d
docker compose exec backend alembic current
docker compose exec backend pytest -v
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/validate_phase9.py"
```

Frontend (host):

```bash
cd frontend && npm install && npm test && npm run build
```

## UI

```bash
docker compose up --build
# UI http://localhost:3000  ·  API http://localhost:8000
```

## Demo / seed

```bash
docker compose exec backend python /scripts/seed_demo_corpus.py
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/demo_generate_fake.py"
```

Full walkthrough: [demo.md](demo.md)

## Observability

```bash
curl -s http://localhost:8000/health/live
curl -s http://localhost:8000/health/ready
curl -s http://localhost:8000/metrics
curl -s http://localhost:8000/api/v1/signals
curl -s http://localhost:8000/api/v1/ops/summary
curl -s http://localhost:8000/api/v1/runbooks
```

## Evaluate

```bash
docker compose exec backend python -m app.cli.retrace eval --suite gold_v1
docker compose exec backend python -m app.cli.retrace eval --suite planted_v1 --suite-version 1.0.0
docker compose exec backend python -m app.cli.retrace baseline promote <experiment_id>
```

For local LLM generation via Ollama, set `MODEL_*` in `.env` (see root `.env.example`). Keep planted/gold suite results separate from live-model robustness claims.

## Migrations

```text
001 … → 006_phase6_experiments_baselines
```

Phases 7–9 add no schema migration.

## Release

See [release.md](release.md).
