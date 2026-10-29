# Judge validation against labeled examples

**Source of these numbers: live model run (llama3.2:latest via http://host.docker.internal:11434/v1).**

Generated 2026-10-26T06:59:03+00:00 by `retrace judges validate` (elapsed 5460.49s). Model `llama3.2:latest` at `http://host.docker.internal:11434/v1`, temperature 0.0, provider class `OpenAICompatibleProvider`.

## Labeled example set

- 66 examples (relevance: 24, faithfulness: 24, contradiction: 18).
- Example-set hash: `sha256:c6d8fc9c8bf2a7344788b8c0f5ad98381dc566000d3370afe1c05c1cda268934`; labels file hash: `sha256:565837c67b72ea6b7c95334ab4cf181c6e4593db082d1bf46350b16af23cdd28`.

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
| relevance | v1 | 51 | chunk relevant | 0.843 | 0.815 | 0.880 | 0.846 | 0.687 | 0.298 | 0.000 | 23087.732 |
| relevance | v1 | 24 | context_sufficient | 0.292 | 1.000 | 0.191 | 0.320 | 0.056 | n/a | 0.000 | 23087.732 |
| relevance | v1b | 51 | chunk relevant | 0.804 | 0.759 | 0.880 | 0.815 | 0.609 | 0.251 | 0.000 | 22016.835 |
| relevance | v1b | 24 | context_sufficient | 0.333 | 1.000 | 0.238 | 0.385 | 0.072 | n/a | 0.000 | 22016.835 |
| relevance | v1c | 51 | chunk relevant | 0.843 | 0.840 | 0.840 | 0.840 | 0.686 | 0.291 | 0.000 | 25286.600 |
| relevance | v1c | 24 | context_sufficient | 0.375 | 1.000 | 0.286 | 0.444 | 0.091 | n/a | 0.000 | 25286.600 |
| faithfulness | v1 | 24 | has unsupported claim | 0.542 | 0.545 | 0.923 | 0.686 | 0.015 | 0.618 | 0.000 | 21298.472 |
| faithfulness | v1 | 24 | score within labeled band | 0.167 | | | | | | | |
| faithfulness | v1b | 24 | has unsupported claim | 0.583 | 0.565 | 1.000 | 0.722 | 0.098 | 0.528 | 0.000 | 24419.259 |
| faithfulness | v1b | 24 | score within labeled band | 0.208 | | | | | | | |
| faithfulness | v1c | 24 | has unsupported claim | 0.583 | 0.565 | 1.000 | 0.722 | 0.098 | 0.653 | 0.000 | 19536.492 |
| faithfulness | v1c | 24 | score within labeled band | 0.167 | | | | | | | |
| contradiction | v1 | 18 | contradicts | 0.889 | 0.818 | 1.000 | 0.900 | 0.778 | n/a | 0.000 | 14770.276 |
| contradiction | v1b | 18 | contradicts | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | n/a | 0.000 | 14206.544 |
| contradiction | v1c | 18 | contradicts | 0.889 | 0.818 | 1.000 | 0.900 | 0.778 | n/a | 0.000 | 16464.823 |

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

- 282 judge calls; schema-failure rate 0.000, other error rate 0.000, retry rate 0.007, mean latency 19317.878 ms, p95 32129.760 ms.
