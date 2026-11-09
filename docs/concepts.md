# Concepts

A plain-English glossary of the words Retrace uses, then the full list of
diagnosis rules. The rule table is generated from
`backend/app/services/diagnosis/rule_catalog.py` by `scripts/gen_concepts.py`,
and a test (`backend/tests/test_concepts_doc.py`) fails if the two disagree.

## Glossary

**RAG (retrieval-augmented generation).** An assistant that first looks up
passages from a document collection, then asks a language model to answer
using only those passages. Retrace diagnoses why such an answer went wrong.

**Corpus and corpus version.** The document collection being searched. Each
ingest creates an immutable corpus version with its own chunks and hash, so a
diagnosis always points at exactly the text that was searched. Traces from
your own app (external traces) have no corpus version.

**Chunk.** A passage cut from a document; the unit that retrieval returns and
the judges read. Retrace's own corpora use 512-character chunks with a
64-character overlap by default.

**Top-k.** How many chunks retrieval returns for a query (5 by default).

**Gold chunk.** A chunk that a person marked as containing the answer. When a
trace carries gold chunk ids, Retrace can tell a retrieval miss (the answer
exists but was not retrieved) from a question the documents cannot answer.

**Distractor.** A retrieved chunk that is off-topic or unofficial, for
example an outdated FAQ with different numbers. Many distractors can crowd
out the evidence.

**Judge.** A component that answers one narrow question about a trace: are
the retrieved chunks relevant (relevance judge), does the answer contradict
them (contradiction judge), is each claim supported (faithfulness judge).
Relevance and contradiction are LLM judges with structured JSON output.

**NLI (natural language inference).** A small model that reads a premise and
a hypothesis and says whether the premise entails, contradicts or is neutral
to it. Retrace's default faithfulness judge uses one
(`cross-encoder/nli-deberta-v3-small`) on CPU, so faithfulness does not need
an LLM call.

**Claim.** One statement from the answer, checked on its own. The NLI judge
splits the answer into sentences and checks each against single sentences
and adjacent sentence pairs of the retrieved chunks.

**Signal bag.** The structured facts the rules read: how many chunks came
back, whether a gold chunk was hit, the fraction of irrelevant chunks,
whether the context is sufficient, whether the answer is an abstention,
claim counts and the faithfulness score.

**Rule.** A fixed condition on the signal bag that, when it holds, names a
failure code. Rules have ids R00 to R99 and are listed below.

**First match.** Rules are checked in order and the first one that holds
decides the diagnosis. A retrieval failure therefore wins over a generation
failure: if the evidence was never retrieved, what the model did with the
wrong chunks is not the root cause.

**Failure code.** The diagnosis itself, such as `RETRIEVAL_MISS` or
`GENERATION_CONTRADICTION`. `OK_*` codes mean nothing went wrong.

**Stage (layer).** Where in the pipeline a failure code points: retrieval,
abstention, generation, grounding, or infra (Retrace or the model could not
run). Because rules are first-match, stages after the one that broke are
not assessed.

**Abstention.** The system declining to answer, for example
"INSUFFICIENT_CONTEXT" or "I don't know". Abstaining is correct when the
retrieved chunks do not hold the answer (`OK_CORRECT_ABSTENTION`) and a
failure when they do (`ABSTENTION_FALSE_POSITIVE`).

**Uncertain diagnosis.** `DIAGNOSIS_UNCERTAIN` (rule R90): the judges ran but
their signals disagree, so Retrace defers to a person instead of guessing.

**Confidence and calibrated confidence.** Each diagnosis has a rule-strength
score: how clearly the signals cleared the rule's thresholds. It is not a
probability by itself. A calibrator fitted on a separate calibration suite
maps it to the observed accuracy of diagnoses with similar scores; that is the
calibrated confidence. How well it is calibrated on real runs is reported in
the benchmark docs.

**Suite.** A versioned set of cases with expected failure codes, stored with
a hash so results can be reproduced: `planted_v1` (one scenario per class),
`heldout_v1` (synthetic signals the rules were not tuned on), `calib_v1`
(for calibration), and `live_v1` (real recorded runs labelled by hand).

**Baseline.** An accepted evaluation run that later runs are compared
against.

**Regression gate.** `retrace eval` compares a run with the baseline and
the suite's thresholds and fails when a metric drops too far.

**Exit codes.** `retrace eval` and `retrace diagnose` return 0 for pass, 1
for a regression (or, for `diagnose --fail-on`, a matching failure code) and
2 for an error such as an invalid suite or trace, so CI can tell a bad
result from a broken run.

**External trace.** A trace from your own RAG app, posted to
`POST /api/v1/traces` or run through `retrace diagnose`. Retrace diagnoses
it from the chunks you send and never consults its own corpus. See
[integrate.md](integrate.md).

## Rules

Checked top to bottom; the first rule whose conditions all hold decides.
Thresholds (`TAU_*`) live in `backend/app/services/diagnosis/thresholds.py`.

<!-- rule-table:start (generated by scripts/gen_concepts.py; do not edit by hand) -->
| Rule | Failure code | Stage | Fires when (all must hold) | Meaning |
| --- | --- | --- | --- | --- |
| R00 | `EVAL_MODEL_TIMEOUT` | infra | `stage_error == TIMEOUT` | Generation or model stage timed out before a usable answer. |
| R01 | `EVAL_JUDGE_MALFORMED` | infra | `judge_schema_ok == false` | A required judge returned malformed output after retry. |
| R02 | `EVAL_MISSING_CONTEXT` | infra | `missing_answer (no answer text, and status is not abstained, timeout or failed)` | Execution has no answer to assess, so no judge runs (ADR-044). |
| R10 | `RETRIEVAL_EMPTY` | retrieval | `n_retrieved == 0` | Retrieval returned zero chunks. |
| R11 | `RETRIEVAL_MISS` | retrieval | `gold_ids present`<br>`gold_hit == false` | Gold-relevant chunk(s) exist but none appear in top-k. |
| R12 | `RETRIEVAL_DISTRACTOR_DOMINANT` | retrieval | `n_retrieved > 0`<br>`irrelevant_frac >= TAU_DISTRACTOR_FRAC`<br>`context_sufficient == false`<br>`answer_is_abstention == true` | Retrieved set is dominated by distractors; system abstained. |
| R14 | `OK_CORRECT_ABSTENTION` | abstention | `context_sufficient == false`<br>`answer_is_abstention == true` | Context insufficient and the system correctly abstained. |
| R20 | `ABSTENTION_FALSE_NEGATIVE` | abstention | `context_sufficient == false`<br>`answer_is_abstention == false` | Context insufficient but the system answered anyway. |
| R21 | `ABSTENTION_FALSE_POSITIVE` | abstention | `context_sufficient == true`<br>`answer_is_abstention == true` | Context was sufficient but the system abstained. |
| R30 | `GENERATION_CONTRADICTION` | generation | `context_sufficient == true`<br>`answer_contradicts_context == true` | Answer conflicts with retrieved evidence (contradiction judge). |
| R31 | `GENERATION_HALLUCINATION` | generation | `context_sufficient == true`<br>`unsupported_claim_count > 0`<br>`faithfulness_score < TAU_FAITHFUL` | Context sufficient but answer invents unsupported content. |
| R33 | `GROUNDING_PARTIAL` | grounding | `context_sufficient == true`<br>`unsupported_claim_count > 0`<br>`supported_claim_count > 0`<br>`answer_contradicts_context == false` | Some claims supported by context, others not. |
| R34 | `GROUNDING_UNSUPPORTED` | grounding | `context_sufficient == true`<br>`unsupported_claim_count > 0`<br>`supported_claim_count == 0` | Answer asserts claims not supported by retrieved context. |
| R40 | `OK_GROUNDED` | none | `context_sufficient == true`<br>`faithfulness_score >= TAU_FAITHFUL`<br>`answer_contradicts_context == false`<br>`answer_is_abstention == false` | Answer is grounded in retrieved evidence. |
| R90 | `DIAGNOSIS_UNCERTAIN` | uncertain | `judges ran`<br>`signals inconsistent: faithfulness_score < TAU_FAITHFUL with unsupported_claim_count == 0, OR a required judge verdict is missing` | Judge outputs are self-inconsistent or incomplete; the engine declines to localize and recommends manual review. |
| R99 | `EVAL_INTERNAL_ERROR` | infra | `no earlier rule matched` | Fallback when no primary rule matched the signal bag. |
<!-- rule-table:end -->
