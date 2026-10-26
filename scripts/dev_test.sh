#!/usr/bin/env sh
# Run backend pytest inside the retrace-backend image with the working-tree
# source bind-mounted over the image copy, so edits are picked up without a
# rebuild. Requires `docker compose up -d postgres chroma` first.
#
#   scripts/dev_test.sh                      # whole suite
#   scripts/dev_test.sh tests/test_phase4_diagnosis.py -k rule
#   scripts/dev_test.sh python -m app.cli.retrace eval --suite planted_v1
#
# On Git Bash (Windows) MSYS path conversion is disabled so the -v mounts are
# passed to Docker verbatim.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    ROOT="$(cd "$ROOT" && pwd -W)"
    export MSYS_NO_PATHCONV=1
    ;;
esac
B="$ROOT/backend"

if [ "$#" -eq 0 ]; then
  set -- pytest -q -p no:cacheprovider
elif [ "${1#tests/}" != "$1" ] || [ "${1#-}" != "$1" ]; then
  set -- pytest -q -p no:cacheprovider "$@"
fi

cd "$ROOT"
exec docker compose run --rm --no-deps \
  -v "$B/app:/app/app" \
  -v "$B/tests:/app/tests" \
  -v "$B/datasets:/app/datasets" \
  -v "$B/configs:/app/configs" \
  -v "$B/alembic:/app/alembic" \
  -v "$B/prompts:/app/prompts" \
  -v "$ROOT/scripts:/scripts:ro" \
  -v "$ROOT/data:/data" \
  -v "$ROOT/docs:/docs" \
  -v "$ROOT/docs/runbooks:/app/runbooks:ro" \
  backend "$@"
