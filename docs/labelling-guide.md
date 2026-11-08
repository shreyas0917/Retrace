# Labelling guide: live_v1

This guide is for labelling the `live_v1` cases by hand. Each case is one real
run of the RAG pipeline: a question, the chunks retrieval returned (in rank
order), and the answer the model gave. Your label says what actually went
wrong, if anything, and where.

You label from `data/labelling/live_v1_sheet.csv`. The same cases are easier
to read in `data/labelling/live_v1_sheet.html`, and every chunk of the corpus
is listed in `data/labelling/live_v1_corpus_chunks.csv`.

## Keep it blind

The sheet does not show how a case was produced or what Retrace predicted.
Please keep it that way while labelling: do not open `runs.jsonl`,
`queries.jsonl` or `corpus_variants.json` in `backend/datasets/suites/live_v1/`,
and do not run Retrace on the cases. A label is only useful if it was made
without seeing the prediction.

## The source of truth

The 13 policy documents in `data/corpus/demo/` are the truth. Their chunks are
the ones in `live_v1_corpus_chunks.csv`. If a retrieved chunk comes from a
document that is not in that list, treat it as unofficial: it may be outdated
or simply wrong, and an answer that relies on it against the 13 policies is
not grounded in the truth.

## Columns you fill in

| Column | What to write |
| --- | --- |
| `failure_label` | One code from the table below. Required. |
| `acceptable_primary_codes` | Other codes that are equally defensible, separated by `;`. Leave empty when only one code fits. `failure_label` always counts as acceptable, so do not repeat it. |
| `gold_chunk_ids` | The chunk ids in `live_v1_corpus_chunks.csv` that contain the answer, separated by `;`. Write `none` if the 13 policies do not answer the question. You may write a document id (for example `refund_policy`) when the whole document is the answer's source; it is expanded to all of that document's chunks. |
| `should_abstain` | `yes` if a careful assistant, given only the retrieved chunks shown, should have said it could not answer; otherwise `no`. |
| `expected_answer` | Optional. A short correct answer, if there is one. |
| `notes` | Optional. Anything that made the case hard; it helps the error analysis. |

## Failure codes in plain English

| Code | Use it when |
| --- | --- |
| `OK_GROUNDED` | The answer is correct, and everything it states is supported by the retrieved chunks. |
| `OK_CORRECT_ABSTENTION` | The retrieved chunks do not contain the answer, and the system said it could not answer. |
| `RETRIEVAL_EMPTY` | No chunks were retrieved at all. |
| `RETRIEVAL_MISS` | The 13 policies do contain the answer, but none of the retrieved chunks do. |
| `RETRIEVAL_DISTRACTOR_DOMINANT` | Most retrieved chunks are off-topic or unofficial, they crowd out useful evidence, and the system abstained because of it. |
| `RETRIEVAL_INSUFFICIENT_CONTEXT` | The retrieved chunks are on topic but stop short: they hold part of what is needed, not enough to answer. |
| `ABSTENTION_FALSE_NEGATIVE` | The retrieved chunks do not contain the answer, but the system answered anyway. |
| `ABSTENTION_FALSE_POSITIVE` | The retrieved chunks do contain the answer, but the system said it could not answer. |
| `GENERATION_CONTRADICTION` | The retrieved chunks contain the answer, and the answer states something that conflicts with them (a different number, duration or rule). |
| `GROUNDING_PARTIAL` | Some of what the answer states is supported by the retrieved chunks and some is not, with nothing that directly conflicts. |
| `GROUNDING_UNSUPPORTED` | The retrieved chunks are enough to answer, but nothing the answer states is supported by them (and nothing directly conflicts). |
| `GENERATION_HALLUCINATION` | Like `GROUNDING_UNSUPPORTED`, but the answer clearly invents specific content: names, numbers or rules that appear nowhere. The two are close; when unsure, put one in `failure_label` and the other in `acceptable_primary_codes`. |
| `EVAL_MODEL_TIMEOUT` | The answer field says the pipeline timed out. |
| `EVAL_INTERNAL_ERROR` | The answer field says the pipeline failed for another reason. |

Not labels: `DIAGNOSIS_UNCERTAIN` (Retrace's way of deferring) and
`EVAL_JUDGE_MALFORMED` (about Retrace's judges, which the sheet does not show).
Reserved codes that the engine does not emit yet are not used either.

## Decision order

Work down the list and stop at the first step that fits. This is the order in
which you would localize a failure by hand: did the pipeline run, did
retrieval find the evidence, did the system answer when it should have, and
did the answer stay true to the evidence.

1. **Did the pipeline run?** If the answer field reports a timeout or failure,
   use `EVAL_MODEL_TIMEOUT` or `EVAL_INTERNAL_ERROR`.
2. **Was anything retrieved?** If not, `RETRIEVAL_EMPTY`.
3. **Do the 13 policies answer the question at all?** Fill `gold_chunk_ids`
   first. If the answer is in the policies but in none of the retrieved chunks,
   the failure is retrieval: `RETRIEVAL_MISS`, whatever the answer did. When
   the retrieved set is mostly unofficial or off-topic chunks and the system
   abstained, `RETRIEVAL_DISTRACTOR_DOMINANT` may fit better; list the other in
   `acceptable_primary_codes`.
4. **Is the answer in the retrieved chunks?**
   - Not in them (including questions the policies do not answer): if the
     system abstained, `OK_CORRECT_ABSTENTION`; if it answered,
     `ABSTENTION_FALSE_NEGATIVE`. If the chunks are on topic but only partly
     enough, consider `RETRIEVAL_INSUFFICIENT_CONTEXT`.
   - In them, and the system abstained: `ABSTENTION_FALSE_POSITIVE`.
5. **The answer is in the chunks and the system answered. Is it true to them?**
   - Something conflicts with the chunks: `GENERATION_CONTRADICTION`.
   - Some statements supported, some not: `GROUNDING_PARTIAL`.
   - Nothing supported: `GROUNDING_UNSUPPORTED` or `GENERATION_HALLUCINATION`.
   - Everything supported: `OK_GROUNDED`.

Judge statements against the retrieved chunks, not against what you know.
A sentence that is true in the policies but absent from the retrieved chunks
is unsupported. Harmless framing ("According to the policy, ...") is not a
claim. A small rounding or a restatement that means the same thing is
supported.

## Ambiguous cases

Use `acceptable_primary_codes` only when two codes are genuinely defensible:
a reasonable second labeller could pick either. Typical pairs:
`RETRIEVAL_MISS` and `RETRIEVAL_DISTRACTOR_DOMINANT`;
`GROUNDING_UNSUPPORTED` and `GENERATION_HALLUCINATION`;
`GROUNDING_PARTIAL` and `GENERATION_CONTRADICTION` when an extra statement
both adds something and slightly conflicts. If you cannot decide between more
than two, say so in `notes`.

## Worked examples

These are invented (a parking policy that is not in the corpus), so they do
not overlap any live_v1 case.

**1. Grounded.**
Question: "How many visitor parking passes can an employee request per month?"
Retrieved #1: "Employees may request up to 4 visitor parking passes per month
through the facilities portal." Answer: "Up to 4 visitor passes per month,
requested through the facilities portal."
Label: `OK_GROUNDED`; `gold_chunk_ids` the chunk of #1; `should_abstain` no.
Every statement is in chunk #1.

**2. One extra statement.**
Same question and chunk. Answer: "Up to 4 visitor passes per month. Unused
passes roll over to the next month."
Label: `GROUNDING_PARTIAL`. The first sentence is supported, the second appears
nowhere in the retrieved chunks, and it does not conflict with them.
If it had said "up to 6 passes", the label would be
`GENERATION_CONTRADICTION`.

**3. Evidence exists but was not retrieved.**
Question: "Where do contractors park?" The parking policy has a chunk that
answers it, but retrieval returned three chunks about the visitor pass
process. Answer: "INSUFFICIENT_CONTEXT".
Label: `RETRIEVAL_MISS`; `gold_chunk_ids` the contractor chunk;
`should_abstain` yes. Abstaining was the right reaction to what was retrieved,
but the failure is that retrieval missed the evidence. If all three retrieved
chunks had been from an unofficial document, `RETRIEVAL_DISTRACTOR_DOMINANT`
would be a defensible alternative.

## When you are done

Save the CSV in place and tell me. The merge step checks that every row has a
valid `failure_label`, that every code and chunk id exists, and then writes
`backend/datasets/suites/live_v1/v1.0.0/cases.jsonl` with your labels and the
recorded runs, records the annotator as the author, and recomputes the hash.
