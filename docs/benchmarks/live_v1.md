# live_v1: real pipeline runs, labelled blind

> **Labels:** labelled blind by an independent AI annotator (fresh subagent, no access to Retrace predictions); not yet reviewed by a human.

Produced by `retrace benchmark report --suite live_v1` on 2026-11-09. Suite hash `sha256:3d004c818d9095c70bdd32244d9896e99042592f91a4733f1f2019b6e34d8487`, experiment `3bbf5422-1b5a-494d-a845-0dafdc6bdabd`, report commit 93cc9cdad840a463b3ffc376bbbc0c5e54021885-dirty.

50 questions on the 13-document demo corpus ran through real retrieval, generation and judges (llama3.2:latest, temperature 0; NLI faithfulness), recorded 2026-11-08 to 2026-11-08 on commit edffb7f. Labelled on 2026-11-08. Labels: labelled blind by an independent AI annotator (fresh subagent, no access to Retrace predictions); not yet reviewed by a human. The annotator saw only the blind sheet, the labelling guide and the corpus chunks, never the runs or the injected conditions. This report replays the recorded judge outputs, so it is reproducible offline.

## Results

| Metric | Value |
| --- | --- |
| Lenient accuracy (prediction in the label's acceptable codes) | 40.0% (95% CI 26.0% to 52.0%) |
| Strict accuracy (prediction equals the label) | 38.0% (95% CI 26.0% to 50.0%) |
| Macro-F1 over labelled classes | 0.405 (95% CI 0.278 to 0.553) |
| Deferred as uncertain | 0 of 50 (0.0%) |
| Accuracy on the cases not deferred | 40.0% |

Confidence intervals: percentile bootstrap over cases, 2000 resamples, seed 20261108.

The headline is the diagnosis Retrace made with the code that recorded these runs. The abstention sentinel was matched exactly then, so the 8 `unanswerable` runs where the model replied `INSUFFICIENT CONTEXT` (with a space) were read as answers, not abstentions.

### After fixing a parsing bug found during this evaluation

The abstention-parsing bug fixed in ADR-047 was found here. Re-diagnosing the **same recordings** with the fix (no new runs) gives the numbers below. This would be **optimistic and not an independent measurement**: the fix was written after seeing these exact misses. The headline above stays the as-recorded number.

| Metric (same 50 recordings, fix applied) | Value |
| --- | --- |
| Lenient accuracy | 40.0% (95% CI 26.0% to 52.0%) |
| Strict accuracy | 38.0% (95% CI 26.0% to 50.0%) |
| Macro-F1 | 0.405 (95% CI 0.278 to 0.553) |

The fix changes 8 diagnosis(es) (`RETRIEVAL_DISTRACTOR_DOMINANT` 8) and makes **0** more correct, so the headline is unchanged. The fix makes the pipeline recognise these `unanswerable` runs as abstentions, but the rule engine then calls them `RETRIEVAL_DISTRACTOR_DOMINANT` (the retrieved chunks are off-topic and the system abstained) rather than the labelled `OK_CORRECT_ABSTENTION`. That is a second, separate disagreement between a rule and the label, not an error the parsing fix can settle; a human reviewer should decide which code fits an unanswerable question whose retrieval returned only distractors. The fix is in `app/services/abstention.py`.

## Per class (strict)

| Label | Support | Predicted | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `ABSTENTION_FALSE_NEGATIVE` | 0 | 24 | 0.00 | 0.00 | 0.00 |
| `GENERATION_CONTRADICTION` | 3 | 1 | 1.00 | 0.33 | 0.50 |
| `GENERATION_HALLUCINATION` | 0 | 4 | 0.00 | 0.00 | 0.00 |
| `GROUNDING_PARTIAL` | 2 | 2 | 0.00 | 0.00 | 0.00 |
| `OK_CORRECT_ABSTENTION` | 8 | 0 | 0.00 | 0.00 | 0.00 |
| `OK_GROUNDED` | 30 | 12 | 0.92 | 0.37 | 0.52 |
| `RETRIEVAL_MISS` | 7 | 7 | 1.00 | 1.00 | 1.00 |

## By injected condition

The condition is how a run was produced, not its label: a wrong-facts prompt can still give a correct answer.

| Condition | Cases | Lenient | Strict | Deferred | Labels given |
| --- | ---: | ---: | ---: | ---: | --- |
| clean | 15 | 26.7% | 26.7% | 0 | OK_GROUNDED 15 |
| distractors | 7 | 57.1% | 57.1% | 0 | GENERATION_CONTRADICTION 2, OK_GROUNDED 5 |
| extra_unsupported_claim | 6 | 33.3% | 16.7% | 0 | GENERATION_CONTRADICTION 1, GROUNDING_PARTIAL 2, OK_GROUNDED 3 |
| gold_removed | 7 | 100.0% | 100.0% | 0 | RETRIEVAL_MISS 7 |
| unanswerable | 8 | 0.0% | 0.0% | 0 | OK_CORRECT_ABSTENTION 8 |
| wrong_answer_prompt | 7 | 42.9% | 42.9% | 0 | OK_GROUNDED 7 |

## Confusion matrix

Rows are labels, columns are predictions. Columns: `ABS-FN` ABSTENTION_FALSE_NEGATIVE, `GEN-CONTRA` GENERATION_CONTRADICTION, `GEN-HALL` GENERATION_HALLUCINATION, `G-PART` GROUNDING_PARTIAL, `OK-ABS` OK_CORRECT_ABSTENTION, `OK` OK_GROUNDED, `R-MISS` RETRIEVAL_MISS.

| Label \ Predicted | `ABS-FN` | `GEN-CONTRA` | `GEN-HALL` | `G-PART` | `OK-ABS` | `OK` | `R-MISS` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `GENERATION_CONTRADICTION` | 1 | 1 |  |  |  | 1 |  |
| `GROUNDING_PARTIAL` | 2 |  |  |  |  |  |  |
| `OK_CORRECT_ABSTENTION` | 8 |  |  |  |  |  |  |
| `OK_GROUNDED` | 13 |  | 4 | 2 |  | 11 |  |
| `RETRIEVAL_MISS` |  |  |  |  |  |  | 7 |

## Error analysis

One line per miss. Every cause is **suggested**: an automatic first pass that compares the recorded judge signals with what the label implies. None has been confirmed by hand; treat them as hypotheses.

Suggested causes: judge error: contradiction 1, judge error: faithfulness 5, judge error: relevance 16, rule gap 8.

| Case | Condition | Label | Predicted (rule) | Suggested cause | Why |
| --- | --- | --- | --- | --- | --- |
| L02 | clean | `OK_GROUNDED` | `GENERATION_HALLUCINATION` (R31) | judge error: faithfulness | NLI marked 1 claim(s) unsupported |
| L03 | clean | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L05 | clean | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L06 | clean | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L08 | clean | `OK_GROUNDED` | `GENERATION_HALLUCINATION` (R31) | judge error: faithfulness | NLI marked 1 claim(s) unsupported |
| L09 | clean | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L11 | clean | `OK_GROUNDED` (or GROUNDING_PARTIAL) | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L12 | clean | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L13 | clean | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L14 | clean | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L15 | clean | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L16 | unanswerable | `OK_CORRECT_ABSTENTION` | `ABSTENTION_FALSE_NEGATIVE` (R20) | rule gap | judge signals agree with the label, but the rules map them to ABSTENTION_FALSE_NEGATIVE |
| L17 | unanswerable | `OK_CORRECT_ABSTENTION` | `ABSTENTION_FALSE_NEGATIVE` (R20) | rule gap | judge signals agree with the label, but the rules map them to ABSTENTION_FALSE_NEGATIVE |
| L18 | unanswerable | `OK_CORRECT_ABSTENTION` | `ABSTENTION_FALSE_NEGATIVE` (R20) | rule gap | judge signals agree with the label, but the rules map them to ABSTENTION_FALSE_NEGATIVE |
| L19 | unanswerable | `OK_CORRECT_ABSTENTION` | `ABSTENTION_FALSE_NEGATIVE` (R20) | rule gap | judge signals agree with the label, but the rules map them to ABSTENTION_FALSE_NEGATIVE |
| L20 | unanswerable | `OK_CORRECT_ABSTENTION` | `ABSTENTION_FALSE_NEGATIVE` (R20) | rule gap | judge signals agree with the label, but the rules map them to ABSTENTION_FALSE_NEGATIVE |
| L21 | unanswerable | `OK_CORRECT_ABSTENTION` | `ABSTENTION_FALSE_NEGATIVE` (R20) | rule gap | judge signals agree with the label, but the rules map them to ABSTENTION_FALSE_NEGATIVE |
| L22 | unanswerable | `OK_CORRECT_ABSTENTION` | `ABSTENTION_FALSE_NEGATIVE` (R20) | rule gap | judge signals agree with the label, but the rules map them to ABSTENTION_FALSE_NEGATIVE |
| L23 | unanswerable | `OK_CORRECT_ABSTENTION` | `ABSTENTION_FALSE_NEGATIVE` (R20) | rule gap | judge signals agree with the label, but the rules map them to ABSTENTION_FALSE_NEGATIVE |
| L31 | distractors | `GENERATION_CONTRADICTION` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain; also: judge error: contradiction |
| L33 | distractors | `GENERATION_CONTRADICTION` | `OK_GROUNDED` (R40) | judge error: contradiction | contradiction judge did not flag the conflict |
| L34 | distractors | `OK_GROUNDED` | `GENERATION_HALLUCINATION` (R31) | judge error: faithfulness | NLI marked 1 claim(s) unsupported |
| L38 | wrong_answer_prompt | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L39 | wrong_answer_prompt | `OK_GROUNDED` | `GENERATION_HALLUCINATION` (R31) | judge error: faithfulness | NLI marked 1 claim(s) unsupported |
| L42 | wrong_answer_prompt | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L44 | wrong_answer_prompt | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L45 | extra_unsupported_claim | `OK_GROUNDED` | `GROUNDING_PARTIAL` (R33) | judge error: faithfulness | NLI marked 1 claim(s) unsupported |
| L46 | extra_unsupported_claim | `GROUNDING_PARTIAL` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L47 | extra_unsupported_claim | `OK_GROUNDED` | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |
| L50 | extra_unsupported_claim | `GROUNDING_PARTIAL` (or OK_GROUNDED) | `ABSTENTION_FALSE_NEGATIVE` (R20) | judge error: relevance | relevance judge said the context was insufficient; the label says the system should not abstain |

## Limits

- 50 cases. The confidence intervals above are wide; differences of a few cases are not meaningful.
- One generation and judge model on one small, synthetic policy corpus. Other models and real document collections will behave differently.
- One labeller, an independent AI annotator; no human has reviewed its labels yet, and label noise is not measured. Human review is planned.
- The runs were recorded on a shared, heavily loaded developer machine with the model timeout set to 600 s so that contention would not create timeouts; 0 run(s) timed out. Latency in these runs means nothing.
- Conditions were injected on purpose (removed documents, near-topic distractors, faulty prompts), so the mix of failures is not the mix a production system would see.
- Confidence is calibrated on the synthetic `calib_v1` suite (calib_v1@1.0.0 (sha256:1e1807ab544c7c05fcc1ae9ee5b501dc383536f7d7b3c72b8f9ce92c0b928d2e)); this report does not recalibrate on live data.

## What this does and doesn't show

- **Shows:** how often Retrace's first-match diagnosis agrees with a blind label on 50 real runs of one pipeline, with intervals that say how much that agreement could move with a different sample.
- **Shows:** which kinds of failure it gets right and which it confuses (per-class table, confusion matrix), and where the misses come from (suggested causes above).
- **Does not show:** accuracy on other models, other corpora, or failures that occur naturally in production. One model, a 13-document synthetic policy corpus, and faults injected on purpose.
- **Does not show:** agreement between labellers. There is one label per case, from an AI annotator that no human has reviewed yet.
- **Does not show:** that the confidence score is calibrated on real runs (see the calibration report).
