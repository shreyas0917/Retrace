.PHONY: up down logs test migrate health seed eval

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f backend

migrate:
	docker compose exec backend alembic upgrade head

test:
	docker compose exec backend pytest -v

seed:
	docker compose exec backend python /scripts/seed_demo_corpus.py

eval:
	docker compose exec backend python -m app.cli.retrace eval --suite $(or $(SUITE),planted_v1)

health:
	curl -s http://localhost:8000/health/live
	@echo
	curl -s http://localhost:8000/health/ready
	@echo
