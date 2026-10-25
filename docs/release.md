# Release readiness (Phase 9)

Checklist for presenting Retrace as a finished engineering project.

## Clean-room start

```bash
cp .env.example .env
docker compose down -v
docker compose build
docker compose up -d
```

Wait until backend is healthy, then:

```bash
docker compose exec backend alembic current
# expect: 006_phase6_experiments_baselines (head)
```

## Automated validation

```bash
docker compose exec backend pytest -v
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/validate_phase9.py"
```

Frontend (host):

```bash
cd frontend && npm install && npm test && npm run build
```

## Manual UI smoke

1. http://localhost:3000 loads
2. Navigate Investigate / Evaluations / Experiments / Operations
3. Load an `execution_id` from validation or demo script
4. Confirm diagnosis code + rule visible

## Release artifacts

| Item | Location |
| ---- | -------- |
| Architecture | `docs/architecture.md` |
| Development | `docs/development.md` |
| Demo script | `docs/demo.md` |
| Runbooks | `docs/runbooks/` |
| ADRs | `docs/decisions.md` |
| Demo corpus | `data/corpus/demo/` |
| Suites | gold_v1 / planted_v1 (backend eval data) |

## Explicit limitations

1. Evaluation is primarily offline fixtures + scripted judges.
2. Operational metrics are in-memory (not durable).
3. Results do not prove live-LLM robustness.
4. Results do not prove production-scale reliability.
5. No Kubernetes / cloud deploy / auto-remediation in this release.

## Version

Application version: 0.9.0 (Phases 1–9 complete).

No Phase 10 is defined for this project scope.
