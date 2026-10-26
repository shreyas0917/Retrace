# Held-out diagnosis benchmark: `heldout_v1@1.0.0`

Generated 2026-10-25T20:05:46Z by `retrace benchmark report` · app 1.0.0

This suite was generated independently of the rule engine (labels come from scenario semantics, see `scripts/build_heldout_suite.py`) and is never used to tune rules or thresholds. Roughly 15% of cases sit on decision boundaries on purpose. Fixtures are synthetic with scripted judge outputs: the numbers measure the **diagnosis engine**, not live-LLM robustness.

## Headline

| Metric | Value |
| --- | --- |
| Cases | 160 |
| Suite hash | `sha256:246f8d8e4663f63c3bfd370998fcb5fce0cbccfc3f9497d1e3fd59b28fd5f1a6` |
| Accuracy (lenient: predicted ∈ acceptable codes) | 98.1% |
| Accuracy (strict: predicted == label) | 93.1% |
| Rule-id accuracy | 93.1% |
| Evidence accuracy | 100.0% |
| Macro-F1 | 0.947 |
| Micro-F1 | 0.940 |
| Weighted-F1 | 0.940 |
| Uncertain (deferred) rate | 1.9% |
| Selective accuracy (answered cases only) | 100.0% at 98.1% coverage |
| Gate | PASS (exit 0) |

## Per-class precision / recall / F1

| Expected label | Support | Precision | Recall | F1 | FP | FN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `ABSTENTION_FALSE_NEGATIVE` | 16 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| `ABSTENTION_FALSE_POSITIVE` | 12 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| `DIAGNOSIS_UNCERTAIN` | 0 | 0.000 | 0.000 | 0.000 | 3 | 0 |
| `EVAL_JUDGE_MALFORMED` | 4 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| `EVAL_MODEL_TIMEOUT` | 4 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| `GENERATION_CONTRADICTION` | 16 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| `GENERATION_HALLUCINATION` | 16 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| `GROUNDING_PARTIAL` | 14 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| `OK_CORRECT_ABSTENTION` | 18 | 0.812 | 0.722 | 0.765 | 3 | 5 |
| `OK_GROUNDED` | 18 | 1.000 | 0.833 | 0.909 | 0 | 3 |
| `RETRIEVAL_DISTRACTOR_DOMINANT` | 12 | 0.643 | 0.750 | 0.692 | 5 | 3 |
| `RETRIEVAL_EMPTY` | 10 | 1.000 | 1.000 | 1.000 | 0 | 0 |
| `RETRIEVAL_MISS` | 20 | 1.000 | 1.000 | 1.000 | 0 | 0 |

## Confusion matrix (rows = expected, columns = predicted)

| | ABS-FN | ABS-FP | UNCERTAIN | E-MALFORM | E-TIMEOUT | GEN-CONTRA | GEN-HALL | G-PART | OK-ABS | OK | R-DISTR | R-EMPTY | R-MISS |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ABS-FN | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ABS-FP | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| UNCERTAIN | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E-MALFORM | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| E-TIMEOUT | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GEN-CONTRA | 0 | 0 | 0 | 0 | 0 | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| GEN-HALL | 0 | 0 | 0 | 0 | 0 | 0 | 16 | 0 | 0 | 0 | 0 | 0 | 0 |
| G-PART | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 14 | 0 | 0 | 0 | 0 | 0 |
| OK-ABS | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 13 | 0 | 5 | 0 | 0 |
| OK | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 0 |
| R-DISTR | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 9 | 0 | 0 |
| R-EMPTY | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 10 | 0 |
| R-MISS | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 20 |

Abbreviations: ABS-FN = `ABSTENTION_FALSE_NEGATIVE`, ABS-FP = `ABSTENTION_FALSE_POSITIVE`, UNCERTAIN = `DIAGNOSIS_UNCERTAIN`, E-MALFORM = `EVAL_JUDGE_MALFORMED`, E-TIMEOUT = `EVAL_MODEL_TIMEOUT`, GEN-CONTRA = `GENERATION_CONTRADICTION`, GEN-HALL = `GENERATION_HALLUCINATION`, G-PART = `GROUNDING_PARTIAL`, OK-ABS = `OK_CORRECT_ABSTENTION`, OK = `OK_GROUNDED`, R-DISTR = `RETRIEVAL_DISTRACTOR_DOMINANT`, R-EMPTY = `RETRIEVAL_EMPTY`, R-MISS = `RETRIEVAL_MISS`

## Confidence calibration

Calibrator: histogram binning fitted on `calib_v1` (80 cases, disjoint from this suite), stored in `backend/configs/calibration.json`.

| | Raw rule score | Calibrated confidence |
| --- | ---: | ---: |
| Expected calibration error (lower is better) | 0.128 | 0.004 |
| Brier score (lower is better) | 0.047 | 0.011 |

Reliability bins on this suite (calibrated confidence):

| Bin | Count | Mean confidence | Empirical accuracy |
| --- | ---: | ---: | ---: |
| 0.6–0.7 | 7 | 0.667 | 0.571 |
| 0.9–1.0 | 153 | 1.000 | 1.000 |

## Classifier comparison on identical signal bags

Every classifier receives the exact signal bag the rule engine saw (retrieval counts, gold hit, judge verdicts). `majority` predicts the most common label; `heuristic` uses four cheap non-judge branches; `llm` prompts the configured model with the signals and the taxonomy.

| Classifier | Lenient acc. | Strict acc. | Macro-F1 | Weighted-F1 | Uncertain rate | Malformed | Mean latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `rule_engine` | 98.1% | 93.1% | 0.947 | 0.940 | 1.9% | 0 | 0.3 ms |
| `majority` | 12.5% | 12.5% | 0.019 | 0.028 | 0.0% | 0 | 0.0 ms |
| `heuristic` | 48.1% | 46.2% | 0.414 | 0.346 | 0.0% | 0 | 0.0 ms |
| `llm` | 40.6% | 40.6% | 0.421 | 0.326 | 0.0% | 0 | 9066.4 ms |

LLM classifier: model `llama3.2:latest`, prompt `classifier.v2`, temperature 0.

| Pair | Raw agreement | Cohen's kappa |
| --- | ---: | ---: |
| `rule_engine~majority` | 12.5% | 0.000 |
| `rule_engine~heuristic` | 43.1% | 0.372 |
| `rule_engine~llm` | 40.6% | 0.344 |
| `majority~heuristic` | 12.5% | 0.000 |
| `majority~llm` | 2.5% | 0.000 |
| `heuristic~llm` | 15.0% | 0.140 |

Rule-engine replay consistency (re-applying rules to stored signals reproduces the stored decision): 100.0%.

## Misclassified cases (3)

| Case | Expected | Predicted | Rule | Calibrated conf. | Deferred | Tags |
| --- | --- | --- | --- | ---: | --- | --- |
| H012 | `OK_GROUNDED` | `DIAGNOSIS_UNCERTAIN` | R90 | 0.67 | yes | it_acceptable_use, none, boundary |
| H144 | `OK_GROUNDED` | `DIAGNOSIS_UNCERTAIN` | R90 | 0.67 | yes | benefits_overview, none, boundary |
| H151 | `OK_GROUNDED` | `DIAGNOSIS_UNCERTAIN` | R90 | 0.67 | yes | procurement_policy, none, boundary |

Example explanations produced by the engine for misclassified cases:

- **H012**: Retrieved 1 chunk(s); gold-relevant chunk(s) present (recall@k 1.00); relevance judge marked 1/1 chunk(s) relevant (0% irrelevant) and judged the context sufficient; The system answered; faithfulness 0.83 with 4 supported / 0 unsupported claim(s) (within 0.05 of the 0.85 threshold); the contradiction judge found no conflict. Rule R90 therefore classifies this as DIAGNOSIS_UNCERTAIN (low confidence, score 0.30). The judge outputs do not support a confident localization; manual review is recommended.
- **H144**: Retrieved 4 chunk(s); gold-relevant chunk(s) present (recall@k 1.00); relevance judge marked 1/4 chunk(s) relevant (75% irrelevant, at or above the 70% distractor threshold) and judged the context sufficient; The system answered; faithfulness 0.82 with 4 supported / 0 unsupported claim(s) (within 0.05 of the 0.85 threshold); the contradiction judge found no conflict. Rule R90 therefore classifies this as DIAGNOSIS_UNCERTAIN (low confidence, score 0.30). The judge outputs do not support a confident localization; manual review is recommended.
- **H151**: Retrieved 1 chunk(s); gold-relevant chunk(s) present (recall@k 1.00); relevance judge marked 1/1 chunk(s) relevant (0% irrelevant) and judged the context sufficient; The system answered; faithfulness 0.82 with 4 supported / 0 unsupported claim(s) (within 0.05 of the 0.85 threshold); the contradiction judge found no conflict. Rule R90 therefore classifies this as DIAGNOSIS_UNCERTAIN (low confidence, score 0.30). The judge outputs do not support a confident localization; manual review is recommended.

## Label distribution

| Label | Cases |
| --- | ---: |
| `ABSTENTION_FALSE_NEGATIVE` | 16 |
| `ABSTENTION_FALSE_POSITIVE` | 12 |
| `EVAL_JUDGE_MALFORMED` | 4 |
| `EVAL_MODEL_TIMEOUT` | 4 |
| `GENERATION_CONTRADICTION` | 16 |
| `GENERATION_HALLUCINATION` | 16 |
| `GROUNDING_PARTIAL` | 14 |
| `OK_CORRECT_ABSTENTION` | 18 |
| `OK_GROUNDED` | 18 |
| `RETRIEVAL_DISTRACTOR_DOMINANT` | 12 |
| `RETRIEVAL_EMPTY` | 10 |
| `RETRIEVAL_MISS` | 20 |

## How to reproduce

```bash
python scripts/build_heldout_suite.py --check
docker compose exec backend python -m app.cli.retrace benchmark report --suite heldout_v1 --calibrate-on calib_v1 --markdown /docs/benchmarks/heldout_v1.md
# add --with-llm to include the LLM classifier (needs MODEL_* configured)
```
