# Runbook: Generation timeout

## Signal

`GENERATION_TIMEOUT_RATE` status `ALERT`

## Meaning

The LLM provider timed out during generation. This is an application / provider failure, not a taxonomy diagnosis of answer quality.

## Check

1. `GET /health/ready` — dependencies
2. Logs: `rag_generation_timeout` with `request_id` / `execution_id`
3. Execution status should be `GENERATION_TIMEOUT` (infra), not `GENERATION_HALLUCINATION`
4. `MODEL_BASE_URL`, `MODEL_TIMEOUT_SECONDS`, provider status

## Actions

- Confirm provider reachability and API key validity
- Increase timeout only if latency is expected
- Retry the same `execution_id` path after provider recovery
- Do not reclassify timeouts as generation hallucination
