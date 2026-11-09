# Demo guide

Retrace is not a chatbot. It diagnoses why a RAG pipeline succeeded or failed, with structured evidence, and ships the measurements that back that claim.

## One-minute story

```text
Query → Retrieval → Generation → Judges → Diagnosis (rule + failure code + rule strength)
      → Evidence + explanation → Eval suites / baselines → Durable ops metrics
```

## Start: `make demo`

Needs Docker with Compose. No LLM is required.

```bash
make demo
```

`make demo` creates `.env` with a generated `API_KEY` if it is missing (an existing `.env` is never changed), runs `docker compose up -d --build`, waits for `/health/ready`, seeds the 13-document demo corpus, posts an example trace and prints:

- the diagnosis of that trace;
- the console URL (http://localhost:3000; the API is on http://localhost:8000);
- where the API key is (`API_KEY` in `.env`);
- an Investigate deep link, `http://localhost:3000/?execution=<id>`.

If the configured model (`MODEL_BASE_URL`) answers, it posts `examples/traces/contradiction.json` and the judges run; otherwise it posts `examples/traces/retrieval_miss.json`, which the rules decide without a judge. The first run builds the backend image (about 17 minutes on the author's machine); later runs take a few minutes. It is safe to run again.

**Default model caveat.** With the default `llama3.2`, two of the three example traces are misdiagnosed. No rule has been changed for this; both are listed in the README's Future work and Known issues.

| Example trace | Expected | With `llama3.2` |
| --- | --- | --- |
| `contradiction.json` | `GENERATION_CONTRADICTION` (R30) | `ABSTENTION_FALSE_NEGATIVE` (R20): the relevance judge calls the context insufficient |
| `correct_abstention.json` | `OK_CORRECT_ABSTENTION` (R14) | `RETRIEVAL_DISTRACTOR_DOMINANT` (R12): R12 is checked before the abstention rule |
| `retrieval_miss.json` | `RETRIEVAL_MISS` (R11) | `RETRIEVAL_MISS` (R11), correct; no judge needed |

The README's worked example shows `qwen2.5-coder:7b` output, which gives R30 on `contradiction.json`. `make demo` prints a line saying so after the deep link when it posts that trace.

## Demo path (about 12 minutes)

### 1. Sign in to the console

Open the deep link `make demo` printed. The console asks for the operator API key once and exchanges it for a short-lived session cookie; the key is never stored in the browser bundle. Use the `API_KEY` value from `.env`.

### 2. Investigate the posted trace

The deep link opens Investigate on the trace `make demo` posted. Point out:

- Failure code, rule id and **rule strength** (High / Medium / Low). Its tooltip gives the observed accuracy per strength level on the live runs. There is no calibrated percentage: the committed calibrator was fitted on synthetic data and is miscalibrated on real runs ([calibration report](benchmarks/calibration_live_v1.md)).
- The "Why" sentence: a templated explanation built from the signals, not model prose.
- The `UNCERTAIN — manual review` badge when the engine declines to localize.
- Retrieval evidence (expected / relevant / distractor / missing), `injection_flags` on chunks.
- Judges, evidence references, timeline, raw JSON.

### 3. Import a trace

Console → **Import a trace**. Either click **Load example** (it fills in `examples/traces/contradiction.json`) or paste one of the files in `examples/traces/`:

- `contradiction.json`: the answer contradicts a retrieved chunk;
- `correct_abstention.json`: the system refuses because the chunks do not answer;
- `retrieval_miss.json`: the gold chunk was not retrieved;
- `batch.jsonl`: several traces, for `POST /api/v1/traces/batch` or `retrace diagnose --batch`.

The form checks for obvious mistakes (invalid JSON, a missing `query`, `answer` or `retrieved_chunks`, a chunk without `chunk_id` or `text`), sends the trace to `POST /api/v1/traces` and opens the result. Remember the table above: with `llama3.2`, the first two are misdiagnosed. The same from the command line:

```bash
docker compose exec backend python -m app.cli.retrace diagnose --file /examples/traces/retrieval_miss.json
```

### 4. Live and held-out benchmarks

The live benchmark is the measure of the whole system on 50 real runs; it replays recorded judge outputs, so no model is called:

```bash
scripts/dev_test.sh python -m app.cli.retrace benchmark report --suite live_v1 \
  --markdown /docs/benchmarks/live_v1.md --out /data/reports/live_v1_report.json
```

Show `docs/benchmarks/live_v1.md`: 40.0% lenient accuracy with its confidence interval, the per-condition table and the error analysis. Its labels come from an independent AI annotator and have not yet been reviewed by a human.

The held-out suite is an engine logic test on synthetic signals:

```bash
docker compose exec backend python -m app.cli.retrace eval --suite heldout_v1
```

Or UI Evaluations → suite `heldout_v1` → Run evaluation. Show the per-class precision/recall/F1 table, strict vs lenient accuracy and the deferred (uncertain) rate. The full report with the classifier comparison is in `docs/benchmarks/heldout_v1.md`; regenerate it with:

```bash
docker compose exec backend python -m app.cli.retrace benchmark report \
  --suite heldout_v1 --calibrate-on calib_v1 --markdown /docs/benchmarks/heldout_v1.md
```

### 5. Retrieval and judge measurements

```bash
docker compose exec backend python -m app.cli.retrace retrieval-eval --corpus-dir /data/corpus/demo
docker compose exec backend python -m app.cli.retrace judges validate --limit 20
```

Show `docs/benchmarks/retrieval_ablation.md` (Recall@k, MRR, nDCG across chunking configs, dense vs BM25 vs hybrid) and `docs/benchmarks/judge_validation.md` (judge agreement with labels, both faithfulness backends, prompt sensitivity).

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

## Alternative: manual setup

Use this instead of `make demo` to see each step.

```bash
cp .env.example .env   # set API_KEY; MODEL_* defaults target local Ollama
docker compose up --build -d
docker compose exec backend python /scripts/seed_demo_corpus.py
```

The seed prints the READY corpus version and retrieval ranks for the PTO query. Then, in the console:

1. Investigate → refresh corpora → select the demo READY version.
2. Query: `How much PTO do full-time employees accrue per month?`
3. Generate + diagnose (needs a reachable model; local Ollama works out of the box). Without a model:

```bash
docker compose exec -T backend sh -c "cd /app && PYTHONPATH=/app python /scripts/demo_generate_fake.py"
```

Paste the printed `execution_id` into Investigate → Load, and continue from step 2 above.

## What not to claim

- High accuracy on real runs: `live_v1` is 40.0% lenient with `llama3.2`, on labels not yet reviewed by a human. The held-out suite's 98.1% measures the diagnosis engine on scripted judge outputs, not live-LLM robustness.
- A calibrated probability that a diagnosis is right: the console shows rule strength because the committed calibrator is miscalibrated on real runs.
- Autonomous remediation.
- Production-scale reliability beyond the documented load test on a single developer machine.
