# Demo guide

Retrace is not a chatbot. It diagnoses why a RAG pipeline succeeded or failed, with structured evidence.

## One-minute story

```text
Query → Retrieval → Generation → Judges → Diagnosis (rule + failure code) → Evidence → Eval/Baseline → Ops
```

## Prerequisites

```bash
cp .env.example .env   # if needed
docker compose up --build -d
```

UI: http://localhost:3000 · API: http://localhost:8000  
Default API key: value of `API_KEY` in `.env` (see `.env.example`).

## Demo path (≈10 minutes)

### 1. Seed demo corpus

```bash
docker compose exec backend python /scripts/seed_demo_corpus.py
```

Shows READY version + retrieval ranks for the PTO query.

### 2. Investigate in the UI

1. Open Investigate
2. Paste API key (top bar)
3. Refresh corpora → select the demo READY version
4. Query: `How much PTO do full-time employees accrue per month?`
5. Generate + diagnose (requires a real `MODEL_API_KEY`, or use FakeLLM script below)

Without a live model key, generate from the container:

```bash
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/demo_generate_fake.py"
```

Then paste the printed `execution_id` into Investigate → Load.

Point out:

- Failure code + rule ID (deterministic rule engine)
- Retrieval evidence table
- Judges (if they ran)
- Evidence references
- Raw JSON (secondary)

### 3. Planted-failure evaluation

```bash
docker compose exec backend python -m app.cli.retrace eval --suite planted_v1
```

Or UI Evaluations → suite `planted_v1` → Run evaluation.

Show PASS / REGRESSION / ERROR and case → Investigate.

### 4. Baseline (explicit)

```bash
docker compose exec backend python -m app.cli.retrace baseline promote <experiment_id>
```

Re-run eval; show comparison against baseline.

### 5. Operations

UI Operations, or:

```bash
curl -s http://localhost:8000/health/ready
curl -s http://localhost:8000/api/v1/signals
curl -s http://localhost:8000/api/v1/ops/summary
```

Call out: metrics are in-memory and reset on restart.

## What not to claim

- Live-LLM production accuracy
- Durable production telemetry
- Autonomous remediation
- That offline fixture 1.0 scores prove online robustness
