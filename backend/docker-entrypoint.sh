#!/bin/sh
set -e

echo "Waiting for PostgreSQL..."
python - <<'PY'
import os, time, sys
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
for i in range(60):
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("PostgreSQL is ready")
        sys.exit(0)
    except Exception as exc:
        print(f"Waiting for Postgres ({i+1}/60): {exc}")
        time.sleep(1)
print("PostgreSQL did not become ready in time", file=sys.stderr)
sys.exit(1)
PY

echo "Running Alembic migrations..."
alembic upgrade head

echo "Starting Retrace backend..."
exec "$@"
