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

87 queries (AI-drafted, not yet reviewed) over the 13-document demo corpus (`data/corpus/demo`):
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

The markdown report regenerates its tables and preserves the
"Interpretation" section between the `<!-- interpretation:start/end -->`
markers.

### What the numbers do and do not show

* They compare configurations fairly on one dataset. They do **not** say how
  the system performs on a real customer corpus: the demo corpus is 13 short,
  clean, synthetic-but-realistic policy documents and the queries were drafted
  by the same AI agent that drafted the documents, and no human has reviewed
  them yet.
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

66 examples (AI-drafted, not yet reviewed; 24 relevance, 24 faithfulness, 18 contradiction)
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

Every row records `annotator: "ai_draft"` and `annotation_date`; the manifest
carries the dataset hash. The labels were drafted by an AI agent and no human
has reviewed them yet. After the author's review the annotator becomes
`ai_draft_author_reviewed` and the manifest records how many labels changed.
There is no inter-annotator agreement figure; that is a known limitation.

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

* They measure one model on 66 AI-drafted, not yet reviewed examples. Kappa on 18
  contradiction examples has wide confidence intervals; treat anything within
  about 0.15 as the same.
* Perfect fixture results (kappa = 1.0 with the oracle provider in tests) prove
  the metric pipeline, not the judges.
* A prompt-variant flip rate that is comparable to the error rate against
  labels means the judge is as sensitive to wording as it is wrong; that is the
  signal to keep prompts frozen and versioned, which is why prompt sha256 is in
  every report.

## Faithfulness backends

Since ADR-045 the faithfulness judge has two backends. The default, `nli`, works claim by claim:

1. **Claims.** The answer is split into sentences by a deterministic splitter. It handles decimals ("1.25 days"), common abbreviations ("e.g.", "Dr."), initials, line breaks and bullet items. Sentences of fewer than three words and refusal sentences ("I don't know...") are dropped, duplicates are removed, and at most 20 claims are kept. If nothing survives but the answer has words, the whole answer is one claim.
2. **Scoring.** Each claim is a hypothesis. The premises are cut from every retrieved chunk: each sentence on its own, and each pair of adjacent sentences for claims that span two. A unit longer than the 512-token limit is cut into overlapping windows on token boundaries. Every claim and premise pair is scored in one batched call by `cross-encoder/nli-deberta-v3-small` at a pinned commit.
3. **Decision.** A claim is supported when entailment is the top of the three labels for at least one premise unit. It is flagged contradicted only when no unit supports it and some unit's top label is contradiction. The score is supported claims divided by claims. Each claim records its best chunk and its highest entailment and contradiction probabilities.

Why sentences rather than whole chunks: small NLI models are trained mostly on one-sentence premises. In a manual check before Phase 2 was committed, this model scored a supporting sentence copied word for word as neutral when it sat inside a three-sentence paragraph, and as entailed when given on its own. Scoring sentence units is the SummaC approach (Laban et al., 2022). The cost is more pairs: roughly claims × (2 × sentences − 1) per chunk. Support takes precedence over contradiction because, with sentence premises, an unrelated sentence of the same chunk ("within 5 business days") can contradict a claim another sentence supports ("within 30 days").

The `llm` backend is the original prompt-based judge. Suites with recorded judge outputs replay them whatever the backend, so synthetic benchmarks stay reproducible.

### Where NLI is expected to be weak

These are known limits of sentence-level entailment models. The validation run will show how much each matters on this data.

- **Numeric reasoning.** "15 days per year" from "1.25 days per month" needs arithmetic, which entailment models do unreliably. A correct derived number may come back unsupported.
- **Paraphrase and implicature.** Claims that restate a policy in different words, or draw an obvious conclusion from it, can be scored neutral rather than entailed.
- **Claims that need two separate facts.** Sentence-level premises cannot verify a claim that needs two non-adjacent sentences, or facts from two different chunks, so those claims come out unsupported. Each claim is checked against one sentence or one adjacent pair at a time, and no single unit holds both facts. "Remote workers can claim $400 for a desk and must submit it within 45 days" combines the Remote Work and Expense policies, and will be scored unsupported even though both halves are true.
- **Claim splitting.** One sentence can hold several claims, and some claims span sentences. The splitter does not decompose further, so a partly wrong sentence counts as one unsupported claim.
- **Pronouns and context.** A sentence such as "It was completed in 1889" loses its subject when scored alone; the adjacent-pair units recover only the previous sentence.
- **Pair cap.** At most `NLI_MAX_PAIRS` (default 500) claim and premise pairs are scored per answer. Chunks are visited from the highest retrieval similarity down, so when the cap is reached the least similar chunks are skipped, and the result records `truncated: true` with `chunks_skipped`. A claim supported only by a skipped chunk comes out unsupported. On one 8-CPU developer machine 2000 pairs took about 65 s, so the default of 500 should cost roughly 16 s in the worst case (scaled, not measured); the recorded live runs used 51 to 146 pairs per answer ([benchmarks/nli_latency.md](benchmarks/nli_latency.md), produced by `scripts/measure_nli_latency.py`). Raise the cap if your answers are long and you can afford the time.
- **Window boundaries.** Only a single sentence longer than the token limit is windowed; a supporting clause that straddles a window edge appears whole in the overlap only if it is shorter than the 64-token overlap.

`retrace judges validate --faithfulness-backend both` measures both backends side by side: per labelled claim, per answer (the same metrics as the LLM judge), and the NLI contradiction flag against the labels and against the LLM contradiction judge. The threshold sweep and cross-validated thresholds are reported for sensitivity only.
