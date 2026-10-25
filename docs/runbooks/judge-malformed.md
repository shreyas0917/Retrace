# Runbook: Judge malformed output

## Signal

`JUDGE_MALFORMED_RATE` status `ALERT`

## Meaning

Evaluation judges returned JSON that failed schema validation after one retry → diagnosis `EVAL_JUDGE_MALFORMED` / R01.

This is an evaluation infrastructure failure, distinct from retrieval/generation quality codes.

## Check

1. Metrics: `judge.malformed` / `judge.attempts`
2. Logs: `judge_schema_invalid` then diagnosis with `EVAL_JUDGE_MALFORMED`
3. Judge model / temperature must remain 0 for MVP determinism

## Actions

- Inspect raw judge output in `judge_results` (truncated in logs)
- Confirm FakeLLM scripts in tests; for live judges check provider JSON mode
- Do not silently accept malformed judge output
