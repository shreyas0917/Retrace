# Judge validation against labeled examples

> **PROVISIONAL — AI-drafted labels, not yet reviewed by the author.** Do not quote these numbers until the review is done.

**Source of these numbers: live model run (llama3.2:latest via http://host.docker.internal:11434/v1).**

Generated 2026-11-08T20:33:13+00:00 by `retrace judges validate` (elapsed 4381.81s). Model `llama3.2:latest` at `http://host.docker.internal:11434/v1`, temperature 0.0, provider class `OpenAICompatibleProvider`.

Labels: AI-drafted, then checked by a second AI agent that saw only the review sheet (0 of 173 labels changed). Not yet reviewed by the author. Two AI passes agreeing is weak evidence that a label is right.

Command: `scripts/dev_test.sh python -m app.cli.retrace judges validate --faithfulness-backend both --markdown /docs/benchmarks/judge_validation.md --out /data/reports/judge_validation.json` (prompt variants v1, v1b, v1c; v1 is production).

## Labeled example set

- 66 examples (relevance: 24, faithfulness: 24, contradiction: 18).
- Example-set hash: `sha256:e46238e914f13c5f8d976d41328c74cb245eedfff104ac008000a9ce67da84c4`; labels file hash: `sha256:19e601ed4821eff6ad110263673d6d08f269104ebe726a331c3311f39a3fca68`.

## Prompt versions

| judge | variant | prompt_version | sha256 |
|---|---|---|---|
| relevance | v1 | relevance.v1 | `sha256:9721be15b22efbdb...` |
| relevance | v1b | relevance.v1b | `sha256:df43ec5b1a6ce1b2...` |
| relevance | v1c | relevance.v1c | `sha256:4bc7917e10f6bafc...` |
| faithfulness | v1 | faithfulness.v1 | `sha256:41de82b4aa636086...` |
| faithfulness | v1b | faithfulness.v1b | `sha256:25d93e1b87fb0135...` |
| faithfulness | v1c | faithfulness.v1c | `sha256:4093ef9b73d4c314...` |
| contradiction | v1 | contradiction.v1 | `sha256:14b8d149deed2202...` |
| contradiction | v1b | contradiction.v1b | `sha256:b549c15caca57751...` |
| contradiction | v1c | contradiction.v1c | `sha256:9b8cc8c9341442ec...` |

## Accuracy vs labels (per judge, per prompt variant)

| judge | variant | n | metric | acc | prec | rec | F1 | kappa | score MAE | schema fail | mean ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| relevance | v1 | 51 | chunk relevant | 0.843 | 0.815 | 0.880 | 0.846 | 0.687 | 0.298 | 0.000 | 23322.330 |
| relevance | v1 | 24 | context_sufficient | 0.292 | 1.000 | 0.191 | 0.320 | 0.056 | n/a | 0.000 | 23322.330 |
| relevance | v1b | 51 | chunk relevant | 0.804 | 0.759 | 0.880 | 0.815 | 0.609 | 0.251 | 0.000 | 19074.565 |
| relevance | v1b | 24 | context_sufficient | 0.333 | 1.000 | 0.238 | 0.385 | 0.072 | n/a | 0.000 | 19074.565 |
| relevance | v1c | 51 | chunk relevant | 0.843 | 0.840 | 0.840 | 0.840 | 0.686 | 0.291 | 0.000 | 17426.288 |
| relevance | v1c | 24 | context_sufficient | 0.375 | 1.000 | 0.286 | 0.444 | 0.091 | n/a | 0.000 | 17426.288 |
| faithfulness | v1 | 24 | has unsupported claim | 0.542 | 0.545 | 0.923 | 0.686 | 0.015 | 0.618 | 0.000 | 21734.036 |
| faithfulness | v1 | 24 | score within labeled band | 0.167 | | | | | | | |
| faithfulness | v1b | 24 | has unsupported claim | 0.583 | 0.565 | 1.000 | 0.722 | 0.098 | 0.528 | 0.000 | 17618.845 |
| faithfulness | v1b | 24 | score within labeled band | 0.208 | | | | | | | |
| faithfulness | v1c | 24 | has unsupported claim | 0.583 | 0.565 | 1.000 | 0.722 | 0.098 | 0.653 | 0.000 | 14421.616 |
| faithfulness | v1c | 24 | score within labeled band | 0.167 | | | | | | | |
| contradiction | v1 | 18 | contradicts | 0.889 | 0.818 | 1.000 | 0.900 | 0.778 | n/a | 0.000 | 14747.922 |
| contradiction | v1b | 18 | contradicts | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | n/a | 0.000 | 10160.307 |
| contradiction | v1c | 18 | contradicts | 0.889 | 0.818 | 1.000 | 0.900 | 0.778 | n/a | 0.000 | 12319.784 |

## Prompt sensitivity (meaning-preserving rewordings)

| judge | variants | units | flip rate | kappa | mean abs score diff |
|---|---|---|---|---|---|
| relevance | v1|v1b | 75 | 0.173 | 0.648 | 0.151 |
| relevance | v1|v1c | 75 | 0.133 | 0.725 | 0.147 |
| relevance | v1b|v1c | 75 | 0.200 | 0.593 | 0.172 |
| faithfulness | v1|v1b | 24 | 0.042 | 0.647 | 0.146 |
| faithfulness | v1|v1c | 24 | 0.042 | 0.647 | 0.062 |
| faithfulness | v1b|v1c | 24 | 0.000 | 1.000 | 0.125 |
| contradiction | v1|v1b | 18 | 0.111 | 0.778 | n/a |
| contradiction | v1|v1c | 18 | 0.111 | 0.766 | n/a |
| contradiction | v1b|v1c | 18 | 0.111 | 0.778 | n/a |

## Inter-judge consistency (production prompts)

Faithfulness and contradiction were both run on 42 examples that carry an answer.

| check | count | meaning |
|---|---|---|
| contradiction_true_but_faithfulness_1 | 1 | contradicts=true while faithfulness_score == 1.0 |
| insufficient_context_but_faithfulness_1 | 2 | context_sufficient=false yet faithfulness_score == 1.0 with >= 1 claim |
| faithfulness_score_claims_mismatch | 5 | faithfulness_score differs from supported/total claims by > 0.05 |
| contradiction_without_evidence | 0 | contradicts=true but chunk_ids is empty |
| relevance_items_missing | 20 | relevance judge omitted or invented chunk ids |

Flagged examples: rel_001 (relevance_items_missing); rel_003 (relevance_items_missing); rel_006 (relevance_items_missing); rel_008 (relevance_items_missing); rel_010 (relevance_items_missing); rel_013 (relevance_items_missing); rel_014 (relevance_items_missing); rel_015 (relevance_items_missing); rel_016 (relevance_items_missing); rel_018 (relevance_items_missing); rel_019 (relevance_items_missing); rel_020 (relevance_items_missing); rel_021 (relevance_items_missing); rel_022 (relevance_items_missing); rel_023 (relevance_items_missing); rel_024 (relevance_items_missing); fai_003 (faithfulness_score_claims_mismatch); fai_004 (faithfulness_score_claims_mismatch); fai_004 (relevance_items_missing); fai_008 (faithfulness_score_claims_mismatch); fai_023 (relevance_items_missing); fai_023 (contradiction_true_but_faithfulness_1); fai_023 (insufficient_context_but_faithfulness_1); fai_024 (faithfulness_score_claims_mismatch); con_007 (insufficient_context_but_faithfulness_1); con_010 (relevance_items_missing); con_014 (faithfulness_score_claims_mismatch); con_017 (relevance_items_missing)

## Reliability over all calls

- 282 judge calls; schema-failure rate 0.000, other error rate 0.000, retry rate 0.007, mean latency 15534.366 ms, p95 27140.730 ms.

## Faithfulness: NLI backend

Model `cross-encoder/nli-deberta-v3-small` at revision `fa2804872c3b4bd748f38c0185cc85775361e735`, decision rule `entailment_is_top_label` (label order read from the model config: contradiction, entailment, neutral). Version `faithfulness.nli.v1`. Example-set hash `sha256:e46238e914f13c5f8d976d41328c74cb245eedfff104ac008000a9ce67da84c4`.

| view | n | acc | prec | rec | F1 | kappa |
|---|---|---|---|---|---|---|
| labelled claims: supported | 56 | 0.875 | 0.973 | 0.857 | 0.911 | 0.702 |
| answers: has unsupported claim | 24 | 0.917 | 0.923 | 0.923 | 0.923 | 0.832 |
| contradiction flag vs labels | 18 | 0.944 | 0.900 | 1.000 | 0.947 | 0.889 |

Answer-level score error (mean absolute): 0.236; share of scores inside the labelled band: 0.583; answers with no checkable claim: 0.

Agreement between the NLI contradiction flag and the LLM contradiction judge on 18 examples: raw 0.833, kappa 0.658.

Side by side on the same examples (has unsupported claim):

| backend | n | acc | prec | rec | F1 | kappa | score MAE | in band |
|---|---|---|---|---|---|---|---|---|
| llm | 24 | 0.542 | 0.545 | 0.923 | 0.686 | 0.015 | 0.618 | 0.167 |
| nli | 24 | 0.917 | 0.923 | 0.923 | 0.923 | 0.832 | 0.236 | 0.583 |

### Entailment threshold sensitivity (not used to choose the rule)

Sensitivity only. The decision rule stays 'entailment is the top label'; these thresholds were not used to choose it.

| entailment threshold | n | acc | kappa |
|---|---|---|---|
| 0.1 | 56 | 0.893 | 0.727 |
| 0.2 | 56 | 0.911 | 0.778 |
| 0.3 | 56 | 0.875 | 0.702 |
| 0.4 | 56 | 0.875 | 0.702 |
| 0.5 | 56 | 0.875 | 0.702 |
| 0.6 | 56 | 0.875 | 0.702 |
| 0.7 | 56 | 0.839 | 0.633 |
| 0.8 | 56 | 0.839 | 0.633 |
| 0.9 | 56 | 0.804 | 0.585 |

Grouped 5-fold cross-validation by example (threshold chosen on the training folds, scored on the held-out fold): mean held-out accuracy 0.889, mean held-out kappa 0.748; chosen thresholds per fold: 0.2, 0.2, 0.5, 0.2, 0.2.

## Limits

- Small sets: 24 relevance, 24 faithfulness (56 claims) and 18 contradiction examples. One or two examples move accuracy by several points, so the confidence intervals are wide; read differences between backends and variants with that in mind.
- The examples are short excerpts of one synthetic policy corpus, written for this test.
- NLI is weak on numeric reasoning (comparing amounts, dates and durations), on claims that need several sentences, and on claims that combine facts from more than one chunk.
- NLI thresholds are the fixed rule (a claim is supported when entailment is the top label); the cross-validated threshold table is a sensitivity check, not a tuned setting.
