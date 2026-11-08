# Use Retrace on your own RAG app

Retrace can diagnose answers produced by any RAG system. Send it a **trace**: the question, the chunks your retriever returned, and the answer your model gave. Retrace stores the trace and runs the same diagnosis engine it uses for its own pipeline. It never looks the chunks up in its own corpus or vector store; the chunk text you send is exactly what the judges read.

## The trace format

```json
{
  "query": "How much PTO do full-time employees accrue per month?",
  "retrieved_chunks": [
    {"chunk_id": "handbook:c001", "text": "Full-time employees accrue 1.25 days...", "score": 0.84, "rank": 1, "source_name": "handbook.md"}
  ],
  "answer": "Full-time employees accrue 3 days of PTO per month.",
  "abstained": false,
  "gold_chunk_ids": ["handbook:c001"],
  "expected_abstention": null,
  "metadata": {"app": "my-rag", "model": "gpt-4.1-mini"},
  "diagnose": true
}
```

| Field | Required | What it affects |
| --- | --- | --- |
| `query` | yes | The question shown to every judge. Control characters are stripped; at most `MAX_QUERY_CHARS` characters. |
| `retrieved_chunks` | no, defaults to `[]` | The only context the judges see. An empty list is diagnosed as `RETRIEVAL_EMPTY` (rule R10) without any judge. At most `MAX_TRACE_CHUNKS` chunks of at most `MAX_TRACE_CHUNK_CHARS` characters each. |
| `chunk_id` | yes, per chunk | Must be unique within the trace and match `^[A-Za-z0-9._:/#-]+$`. Used in evidence references and to check gold chunks. |
| `score`, `rank`, `source_name` | no | Shown in the investigation view. Not used by the rules. `rank` defaults to list order. |
| `document_id` | no | Shown in the investigation view. Defaults to the part of `chunk_id` before the first `:`. |
| `answer` | no | The text the faithfulness and contradiction judges assess. `null` or blank means the app produced no answer: the trace is diagnosed as `EVAL_MISSING_CONTEXT` (rule R02) and no judge runs. |
| `abstained` | no | Whether the app declined to answer. When omitted, Retrace detects abstention as described below. |
| `gold_chunk_ids` | no | The chunks that should have been retrieved. **Without them, retrieval-miss detection (rule R11) is unavailable**, and the response says so in `warnings`. |
| `expected_abstention` | no | Stored with the trace for your own evaluation. Not read by the rules. |
| `metadata` | no | Free-form JSON object, at most 50 keys and 8 KB. A string `model` is shown as the generation model. Not read by the rules. |
| `diagnose` | no, defaults to `true` | `false` stores the trace without diagnosing it. |

Unknown fields are rejected, and booleans must be real JSON booleans. The whole request is also subject to `MAX_REQUEST_BYTES` (1 MiB by default).

### How abstention is detected

When `abstained` is omitted, the answer counts as an abstention if it is exactly Retrace's sentinel `INSUFFICIENT_CONTEXT`, or if it is at most 300 characters long and contains one of these phrases, case-insensitively:

`i don't know`, `i do not know`, `i cannot answer`, `i can't answer`, `i am unable to answer`, `i'm unable to answer`, `not enough information to answer`, `the provided context does not contain`, `the context does not contain`, `the documents do not contain`, `no relevant information`.

The response reports how it decided in `abstention_detected_by` (`explicit`, `sentinel`, `refusal_phrase:<phrase>` or `none`). If your app knows whether it abstained, send `abstained` explicitly.

### Which outcomes need a judge model

Empty retrieval, a gold-chunk miss and a missing answer are decided deterministically, with no LLM call. Every other outcome needs the relevance judge, and answered traces with sufficient context also need the faithfulness and contradiction judges, using the model configured in `MODEL_*`.

## Send one trace

```bash
curl -s -X POST http://localhost:8000/api/v1/traces \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d @examples/traces/retrieval_miss.json
```

The response contains the stored `execution_id`, the `diagnosis` (the same shape as `POST /api/v1/diagnose`), `warnings`, `abstention_detected_by`, and `injection_flags` for any chunk that matched a prompt-injection pattern. Flagged chunks are still passed to the judges unchanged; the flags are evidence for you, not a filter.

## Wrap your RAG function

```python
import httpx

RETRACE = "http://localhost:8000"
HEADERS = {"Authorization": "Bearer YOUR_API_KEY"}

def answer_with_trace(question: str) -> str | None:
    chunks = my_retriever(question)   # your code: [{"id", "text", "score"}, ...]
    answer = my_llm(question, chunks)  # your code: str, or None if generation failed
    trace = {
        "query": question,
        "retrieved_chunks": [
            {"chunk_id": c["id"], "text": c["text"], "score": c["score"], "rank": i + 1}
            for i, c in enumerate(chunks)
        ],
        "answer": answer,
    }
    result = httpx.post(f"{RETRACE}/api/v1/traces", json=trace, headers=HEADERS, timeout=120).json()
    print(result["diagnosis"]["failure_code"], result["execution_id"])
    return answer
```

Open `GET /api/v1/investigations/{execution_id}` for the full evidence. External traces report `"source": "external"` and a null `corpus_version_id`.

## Send many traces

`POST /api/v1/traces/batch` accepts a JSON array (or `{"traces": [...]}`), or JSON Lines with `Content-Type: application/x-ndjson`. At most `MAX_TRACE_BATCH` traces (25 by default); **for larger batches use the CLI** (`retrace diagnose --batch`, below). Each trace is validated and diagnosed independently, so one bad trace does not fail the batch:

```json
{"summary": {"total": 3, "ok": 2, "failed": 1},
 "results": [{"index": 0, "ok": true, "execution_id": "...", "diagnosis": {...}},
             {"index": 1, "ok": false, "error": {"code": "INVALID_REQUEST", "message": "Trace failed validation", "details": {...}}}]}
```

Diagnosis runs inside the request, and a batch that needs LLM judges can take minutes on a slow model. That is why the cap is small: anything bigger belongs in the CLI, which has no batch limit.

## Use it as a CI check

`retrace diagnose` runs in process, like `retrace eval`, and needs no running API:

```bash
python -m app.cli.retrace diagnose --file trace.json
python -m app.cli.retrace diagnose --batch traces.jsonl --fail-on RETRIEVAL_MISS,GENERATION_CONTRADICTION
python -m app.cli.retrace diagnose --batch traces.jsonl --fail-on ALL_FAILURES --json
```

| Exit code | Meaning |
| ---: | --- |
| `0` | Every trace was diagnosed and none matched `--fail-on` |
| `1` | At least one diagnosed failure code is in `--fail-on` |
| `2` | A trace could not be read, validated or diagnosed (this wins over `1`) |

`ALL_FAILURES` matches every code that is not an `OK_*` outcome. The default output is a readable summary per trace (verdict, failure code, rule, confidence, explanation, recommendation); `--json` prints everything. Ready-made inputs live in [`examples/traces/`](../examples/traces/).

## Limits and settings

| Setting | Default | Limits |
| --- | ---: | --- |
| `MAX_TRACE_CHUNKS` | 50 | chunks per trace |
| `MAX_TRACE_CHUNK_CHARS` | 8000 | characters per chunk text |
| `MAX_TRACE_ANSWER_CHARS` | 20000 | characters in the answer |
| `MAX_TRACE_BATCH` | 25 | traces per batch request; use the CLI for more |
| `MAX_QUERY_CHARS` | 4000 | characters in the query |
| `MAX_REQUEST_BYTES` | 1048576 | bytes per request body |

Traces are stored in PostgreSQL, including chunk texts and answers. Do not send data you are not allowed to store there.
