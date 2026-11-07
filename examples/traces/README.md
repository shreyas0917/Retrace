# Example traces

Inputs for `POST /api/v1/traces` and `retrace diagnose`. They show the trace format and the three most common outcomes. They are **not benchmarks**: nothing here measures accuracy, and with a live judge model the result depends on what that model returns.

| File | What the RAG app did | Diagnosis when the judges agree with the setup |
| --- | --- | --- |
| `retrieval_miss.json` | Retrieved two chunks, neither of which is the gold chunk that answers the question | `RETRIEVAL_MISS` (rule R11). Decided from `gold_chunk_ids` alone, so no judge model is needed. |
| `contradiction.json` | Retrieved the right chunk, then answered "3 days" when the chunk says 1.25 days | `GENERATION_CONTRADICTION` (rule R30) when the contradiction judge flags the conflict. |
| `correct_abstention.json` | Retrieved on-topic chunks that do not cover contractors, and declined to answer | `OK_CORRECT_ABSTENTION` (rule R14) when the relevance judge rates the context insufficient. `abstained` is omitted, so Retrace detects the refusal from the answer text. |
| `batch.jsonl` | All three, one per line | One result per trace. |

```bash
# inside the backend container (or via scripts/dev_test.sh)
python -m app.cli.retrace diagnose --file /examples/traces/retrieval_miss.json
python -m app.cli.retrace diagnose --batch /examples/traces/batch.jsonl --fail-on ALL_FAILURES
```

See [docs/integrate.md](../../docs/integrate.md) for the full trace format.
