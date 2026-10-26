# Retrieval quality and judge validation (method)

This document explains *how* Retrace measures two things that are easy to
assert and hard to prove: that retrieval actually finds the right chunks, and
that the LLM judges can be trusted. The measured numbers live in
[`benchmarks/retrieval_ablation.md`](benchmarks/retrieval_ablation.md) and
[`benchmarks/judge_validation.md`](benchmarks/judge_validation.md); this page
is the method and the honest list of caveats.

## Part A: retrieval metrics and ablation

### Why

"We use MiniLM embeddings and ChromaDB" describes a mechanism, not a result.
The retrieval ablation turns the question "is retrieval good?" into numbers
that can be compared across chunking strategies, retrievers and embedding
models **on the same query set**.

### Metrics (`backend/app/services/metrics/retrieval.py`)

All metrics use binary relevance over ranked chunk ids:

| metric | definition |
|---|---|
| Recall@k | relevant chunks in the top k / all relevant chunks |
| Precision@k | relevant chunks in the top k / k |
| Hit@k | 1 if any relevant chunk is in the top k |
| MRR | 1 / rank of the first relevant chunk (0 if none) |
| nDCG@k | DCG with gain 1 and discount 1/log2(rank+1), divided by the ideal DCG for min(|relevant|, k) items |

Queries with no relevant chunk (unanswerable) return `None` for every metric
and are excluded from means; they are reported separately as abstention cases.

Note on Recall@1 vs Hit@1: when a query has two relevant chunks (two documents,
or the same span duplicated in an overlap region) Recall@1 is capped at 0.5 by
construction. Hit@1 is the fairer "was the top result right" number, so the
tables show both.

### Dataset (`backend/datasets/retrieval/demo_qrels_v1.jsonl`)

87 hand-written queries over the 13-document demo corpus (`data/corpus/demo`):
82 answerable (30 easy, 34 medium, 18 hard) and 5 unanswerable. Hard queries
include paraphrases, questions whose answer spans two documents, and hard
negatives that reuse another document's vocabulary or a number that appears in
several policies ("10 business days", "30 days", "$300", "7 years").

Relevance is defined **independently of chunking** so one qrels file serves
every chunk size:

> a chunk is relevant iff its `document_id` matches and the normalized chunk
> text contains the normalized `must_contain` substring (lowercase, whitespace
> collapsed).

`must_contain` is capped at 32 characters, which is the overlap of the smallest
configuration in the grid (256/32); any substring no longer than the overlap is
guaranteed to appear intact in at least one chunk. The runner still reports any
query that ends up with zero matching chunks and excludes it from the means
rather than scoring it as a miss. `manifest.json` carries the sha256 of the
canonical JSONL, computed the same way as the evaluation suites.

### Retrievers (`backend/app/services/retrieval_eval.py`)

* **dense**: exact brute-force cosine similarity in numpy over L2-normalized
  embeddings. Production (`app.services.retrieval`) uses Chroma's HNSW cosine
  index on the same normalized vectors and reports `score = 1 - distance`; for
  a corpus of this size HNSW returns exact neighbours, so the two agree up to
  ANN approximation at larger scale.
* **bm25**: Okapi BM25 implemented in pure Python (k1 = 1.5, b = 0.75,
  lowercase alphanumeric tokens, Lucene-style idf). No new dependency.
* **hybrid_rrf**: reciprocal rank fusion of the dense and BM25 rankings with
  k = 60.

The chunking grid is 256/32, 512/64 (production default) and 1024/128
characters, produced by the production `chunk_text`. Extra embedding models
(`--embedding-models BAAI/bge-small-en-v1.5,sentence-transformers/all-mpnet-base-v2`)
are loaded directly from sentence-transformers, bypassing the Settings lock
that keeps production on MiniLM; a model that cannot be downloaded is recorded
as "not run" instead of producing numbers.

Latency is the per-query scoring time (including query embedding) after one
warm-up call, measured inside the container; it is indicative only.

### Running

```sh
scripts/dev_test.sh python -m app.cli.retrace retrieval-eval \
  --corpus-dir /data/corpus/demo \
  --markdown /docs/benchmarks/retrieval_ablation.md \
  --out /data/reports/retrieval_ablation.json
```

The markdown report regenerates its tables and preserves the hand-written
"Interpretation" section between the `<!-- interpretation:start/end -->`
markers.

### What the numbers do and do not show

* They compare configurations fairly on one dataset. They do **not** say how
  the system performs on a real customer corpus: the demo corpus is 13 short,
  clean, synthetic-but-realistic policy documents and the queries were written
  by the same author who wrote the documents.
* With ~80 queries, differences of a few points in MRR are within noise; only
  consistent gaps across configurations and difficulty levels mean anything.
* Relevance labels are substring-based. A chunk that paraphrases the answer
  without containing the substring is scored as irrelevant, which slightly
  penalizes every retriever equally.

## Part B: judge validation

### Why

The relevance, faithfulness and contradiction judges are LLM calls. Their
output drives diagnosis, so their error rate is part of the system's error
rate. Validation measures that error rate against human labels, checks whether
the judges agree with each other, and checks how much they depend on prompt
wording.

### Labeled dataset (`backend/datasets/judges/judge_labels_v1.jsonl`)

66 hand-labeled examples (24 relevance, 24 faithfulness, 18 contradiction)
built from demo-corpus facts. Chunk texts are excerpts of the corpus documents;
four synthetic "injected" chunks carry prompt-injection text. Hard cases:

* relevance: topical-but-unhelpful chunks (insufficient context), partial
  answers, injection chunks that must be judged on content only (one injection
  chunk is relevant, one is not);
* faithfulness: partially supported answers, numerically wrong answers,
  details that exist in the corpus but not in the provided context, an
  injection chunk telling the judge to mark everything supported;
* contradiction: missing information is not a contradiction, unsupported extra
  detail is not a contradiction, abstentions, unit confusion ($300 per month
  vs per week), same-chunk number confusion (SEV1 15 min vs SEV2 1 hour).

Every row records `annotator: "author"` and `annotation_date`; the manifest
carries the dataset hash. Labels were written by one person, so there is no
inter-annotator agreement figure; that is a known limitation.

### What is measured (`backend/app/services/judges/validation.py`)

Per judge and per prompt variant:

* **relevance**: per-chunk accuracy / precision / recall / F1 / Cohen's kappa
  for `relevant`; the same for `context_sufficient`; MAE between the predicted
  score and the label (1.0 / 0.0); chunks the judge dropped from its output are
  counted as "not relevant" and flagged.
* **faithfulness**: binary detection of "answer has at least one unsupported
  claim" (prediction: any claim unsupported or score < 1); MAE between the
  predicted `faithfulness_score` and the labeled supported/total fraction; the
  share of predictions inside the labeled acceptable band.
* **contradiction**: accuracy / precision / recall / F1 / kappa for `contradicts`.
* **reliability**: schema-failure rate (malformed JSON after the one production
  retry), other error rate, retry rate, mean and p95 latency.

Across judges (production prompts only), on every example that has an answer:
`contradicts=true` with `faithfulness_score=1.0`; `context_sufficient=false`
with `faithfulness_score=1.0` and at least one claim; faithfulness score that
disagrees with its own claim list; contradiction without evidence chunk ids;
relevance output that omits or invents chunk ids.

Prompt sensitivity: each judge is re-run with the meaning-preserving variants
in `backend/app/services/judges/prompt_variants.py` (`v1b`, `v1c`; `v1` is the
production prompt imported from the judge modules, never copied). For every
pair of variants the report gives the label flip rate, Cohen's kappa between
the two runs and the mean absolute score difference.

Every report pins: model name, temperature (0), base URL host, prompt version
and sha256 of every prompt variant sent, the example-set hash, the labels file
hash and a timestamp.

### Running

```sh
# local Ollama from inside the container
scripts/dev_test.sh sh -c "MODEL_BASE_URL=http://host.docker.internal:11434/v1 \
  MODEL_API_KEY=ollama MODEL_NAME=llama3.2:latest MODEL_TIMEOUT_SECONDS=120 \
  python -m app.cli.retrace judges validate \
  --markdown /docs/benchmarks/judge_validation.md \
  --out /data/reports/judge_validation.json"
```

`--limit N` evaluates an interleaved subset, `--variants v1` disables the
sensitivity runs and `--skip-consistency` drops the cross-judge calls. The
markdown report states its source on the first line; fixture-based runs (for
example with `ScriptedJudgeLLM` in tests) are labelled as fixtures and must
never be presented as live-model results.

### What the numbers do and do not show

* They measure one model on 66 author-labeled examples. Kappa on 18
  contradiction examples has wide confidence intervals; treat anything within
  about 0.15 as the same.
* Perfect fixture results (kappa = 1.0 with the oracle provider in tests) prove
  the metric pipeline, not the judges.
* A prompt-variant flip rate that is comparable to the error rate against
  labels means the judge is as sensitive to wording as it is wrong; that is the
  signal to keep prompts frozen and versioned, which is why prompt sha256 is in
  every report.
