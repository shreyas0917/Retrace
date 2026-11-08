#!/usr/bin/env sh
# `make demo`: a running console with one diagnosed trace, from a fresh clone.
#
#   1. create .env from .env.example with a generated API_KEY (only if .env is missing)
#   2. docker compose up -d --build
#   3. wait for /health/ready
#   4. seed the demo corpus (no model call)
#   5. post an example trace to /api/v1/traces
#   6. print the console URL, where the key is, and the Investigate deep link
#
# Safe to run again: an existing .env is never touched, the seed is
# idempotent, and each run posts one more example trace.
# Needs no LLM: if the configured model is unreachable, it posts
# examples/traces/retrieval_miss.json, which the rules decide from gold chunk
# ids alone, instead of examples/traces/contradiction.json.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# Git Bash on Windows rewrites /container/paths into Windows paths; turn that off.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 ;;
esac
API="${RETRACE_API_BASE:-http://localhost:8000}"
CONSOLE="${RETRACE_CONSOLE_URL:-http://localhost:3000}"
READY_TIMEOUT="${DEMO_READY_TIMEOUT:-300}"

step() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nmake demo: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is not installed or not on PATH."
command -v curl >/dev/null 2>&1 || fail "curl is not installed or not on PATH."

# 1. .env
if [ -f .env ]; then
  step ".env exists; leaving it unchanged"
else
  step "Creating .env from .env.example with a generated API_KEY"
  key="$(od -An -tx1 -N24 /dev/urandom | tr -d ' \n')"
  [ -n "$key" ] || fail "could not generate a random API key."
  sed "s/^API_KEY=.*/API_KEY=$key/" .env.example > .env
fi
API_KEY="$(sed -n 's/^API_KEY=//p' .env | tail -n 1 | tr -d '\r"'"'")"
case "$API_KEY" in
  ""|replace-me|your_api_key_here) fail "API_KEY in .env is empty or a placeholder. Set a real value, or delete .env and run make demo again." ;;
esac

# 2. stack
step "Starting the stack (docker compose up -d --build)"
docker compose up -d --build

# 3. readiness
step "Waiting for $API/health/ready (up to ${READY_TIMEOUT}s)"
elapsed=0
until curl -sf -m 5 "$API/health/ready" >/dev/null 2>&1; do
  if [ "$elapsed" -ge "$READY_TIMEOUT" ]; then
    docker compose ps
    fail "the API was not ready after ${READY_TIMEOUT}s. Check: docker compose logs backend"
  fi
  sleep 3
  elapsed=$((elapsed + 3))
done
echo "ready after about ${elapsed}s"

# 4. seed (MODEL_API_KEY cleared so the seed never calls a model)
step "Seeding the demo corpus"
docker compose exec -T -e MODEL_API_KEY= backend python /scripts/seed_demo_corpus.py

# 5. example trace
if docker compose exec -T backend python -c "import os, httpx; httpx.get(os.environ['MODEL_BASE_URL'].rstrip('/') + '/models', timeout=3).raise_for_status()" >/dev/null 2>&1; then
  TRACE=examples/traces/contradiction.json
  note="The judge model answered, so the judges run on this trace."
else
  TRACE=examples/traces/retrieval_miss.json
  note="No judge model is reachable (MODEL_BASE_URL in .env), so this posts a trace the rules decide without one. Start your model and post examples/traces/contradiction.json to see the judges."
fi
step "Posting $TRACE to /api/v1/traces"
response="$(curl -sS -m 300 -X POST "$API/api/v1/traces" \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  --data-binary "@$TRACE")" || fail "posting the trace failed."
execution_id="$(printf '%s' "$response" | sed -n 's/.*"execution_id": *"\([^"]*\)".*/\1/p' | head -n 1)"
[ -n "$execution_id" ] || fail "no execution_id in the response: $response"
code="$(printf '%s' "$response" | sed -n 's/.*"failure_code": *"\([^"]*\)".*/\1/p' | head -n 1)"

step "Done"
echo "$note"
echo "Diagnosis:    ${code:-not diagnosed (see the console)}"
echo "Console:      $CONSOLE"
echo "API key:      API_KEY in .env at the repo root (paste it on the console's sign-in screen)"
echo "Investigate:  $CONSOLE/?execution=$execution_id"
