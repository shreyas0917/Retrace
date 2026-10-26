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

# Expand ${UVICORN_WORKERS} in the CMD (Docker exec-form CMD does not expand
# variables). Default 1 worker. With >1 the in-memory metrics snapshot and the
# in-memory rate limiter are per-process; durable telemetry in Postgres is shared.
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"
case "$UVICORN_WORKERS" in
  ''|*[!0-9]*) echo "UVICORN_WORKERS must be a positive integer (got '$UVICORN_WORKERS'); using 1" >&2; UVICORN_WORKERS=1 ;;
  0) UVICORN_WORKERS=1 ;;
esac
export UVICORN_WORKERS
# Rotate the positional args once, substituting the placeholder (preserves
# arguments that contain spaces, e.g. pytest -k "a and b" via dev_test.sh).
_n=$#
_i=0
while [ "$_i" -lt "$_n" ]; do
  _arg=$1
  shift
  case "$_arg" in
    '${UVICORN_WORKERS}') set -- "$@" "$UVICORN_WORKERS" ;;
    *) set -- "$@" "$_arg" ;;
  esac
  _i=$((_i + 1))
done

echo "Starting Retrace backend (uvicorn workers: $UVICORN_WORKERS)..."
exec "$@"
