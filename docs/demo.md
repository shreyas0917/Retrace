# Demo guide

Retrace is not a chatbot. It diagnoses why a RAG pipeline succeeded or failed, with structured evidence, and ships the measurements that back that claim.

## One-minute story

```text
Query → Retrieval → Generation → Judges → Diagnosis (rule + failure code + calibrated confidence)
      → Evidence + explanation → Eval suites / baselines → Durable ops metrics
```

## Prerequisites

```bash
cp .env.example .env   # set API_KEY; MODEL_* defaults target local Ollama
docker compose up --build -d
```

UI: http://localhost:3000 · API: http://localhost:8000

## Demo path (about 12 minutes)

### 1. Sign in to the console

Open http://localhost:3000. The console asks for the operator API key once and exchanges it for a short-lived session cookie; the key is never stored in the browser bundle. Use the `API_KEY` value from `.env`.

### 2. Seed the demo corpus

```bash
docker compose exec backend python /scripts/seed_demo_corpus.py
```

Prints the READY corpus version and retrieval ranks for the PTO query. The demo corpus now has 12 policy documents.

### 3. Investigate an execution

1. Investigate → refresh corpora → select the demo READY version.
2. Query: `How much PTO do full-time employees accrue per month?`
3. Generate + diagnose (needs a reachable model; local Ollama works out of the box). Without a model:

```bash
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/demo_generate_fake.py"
```

Paste the printed `execution_id` into Investigate → Load. Point out:

- Failure code, rule id, rule-strength confidence and the calibrated probability.
- The "Why" sentence: a templated explanation built from the signals, not model prose.
- The `UNCERTAIN — manual review` badge when the engine declines to localize.
- Retrieval evidence (expected / relevant / distractor / missing), `injection_flags` on chunks.
- Judges, evidence references, timeline, raw JSON.

### 4. Held-out benchmark

```bash
docker compose exec backend python -m app.cli.retrace eval --suite heldout_v1
```

Or UI Evaluations → suite `heldout_v1` → Run evaluation. Show the per-class precision/recall/F1 table, strict vs lenient accuracy and the deferred (uncertain) rate. The full report with calibration and the classifier comparison is in `docs/benchmarks/heldout_v1.md`; regenerate it with:

```bash
docker compose exec backend python -m app.cli.retrace benchmark report \
  --suite heldout_v1 --calibrate-on calib_v1 --markdown /docs/benchmarks/heldout_v1.md
```

### 5. Retrieval and judge measurements

```bash
docker compose exec backend python -m app.cli.retrace retrieval-eval --corpus-dir /data/corpus/demo
docker compose exec backend python -m app.cli.retrace judges validate --limit 20
```

Show `docs/benchmarks/retrieval_ablation.md` (Recall@k, MRR, nDCG across chunking configs, dense vs BM25 vs hybrid) and `docs/benchmarks/judge_validation.md` (judge agreement with labels, prompt sensitivity).

### 6. Baseline (explicit)

```bash
docker compose exec backend python -m app.cli.retrace baseline promote <experiment_id>
```

Re-run eval; show the comparison and the exit code.

### 7. Operations

UI Operations, or:

```bash
curl -s http://localhost:8000/health/ready
curl -s http://localhost:8000/api/v1/metrics/durable?window_minutes=60
curl -s http://localhost:8000/api/v1/signals
```

Call out: p50/p95/p99 latency, error rate, token usage and estimated cost come from the durable PostgreSQL store and survive restarts (`docker compose restart backend` then refresh). Load-test numbers are in `docs/benchmarks/load_test.md`.

## What not to claim

- Live-LLM production accuracy: the held-out suite measures the diagnosis engine on scripted judge outputs; judge quality is measured separately and depends on the model.
- Autonomous remediation.
- Production-scale reliability beyond the documented load test on a single developer machine.
