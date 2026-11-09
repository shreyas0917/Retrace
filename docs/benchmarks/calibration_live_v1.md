# Calibration on live_v1, cross-validated

> **Labels: labelled blind by an independent AI annotator (fresh subagent, no access to Retrace predictions); not yet reviewed by a human.**

Produced by `retrace benchmark calibration-cv --suite live_v1 --folds 5 --bins 10 --markdown /docs/benchmarks/calibration_live_v1.md`. Suite hash `sha256:3d004c818d9095c70bdd32244d9896e99042592f91a4733f1f2019b6e34d8487`, commit c8f03b42a6f3e2a775853addd3470aefd917dec9-dirty. Labels: labelled blind by an independent AI annotator (fresh subagent, no access to Retrace predictions); not yet reviewed by a human. The annotator saw only the blind sheet, the labelling guide and the corpus chunks, never the runs or the injected conditions.

50 cases, 5-fold cross-validation (stratified on correct/incorrect; fold sizes 10, 10, 10, 10, 10; seed 20261109). Diagnosis accuracy (strict) on these cases: 40.0%. The histogram calibrator (10 equal-width bins) is fitted on four folds and applied to the fifth, so no case is scored by a calibrator that saw it.

The raw score takes **2 distinct values** (0.7, 1), so any calibrator can only map those few values to probabilities.

## Observed accuracy by rule-strength level

This is what the raw `diagnosis_score` actually predicts on the live runs: the share of correct diagnoses among the cases at each score, with a 95% Wilson interval. It is the honest summary of the confidence signal — a level, not a calibrated percentage.

| Raw score | Cases | Observed accuracy (95% CI) |
| ---: | ---: | --- |
| 0.70 | 31 | 6.5% (2% to 21%) |
| 1.00 | 19 | 94.7% (75% to 99%) |

## Pooled results

Lower is better. 95% CIs: percentile bootstrap over cases (2000 resamples, seed 20261109), with the fold assignment fixed.

| Predictor | ECE | Brier | ECE minus raw | Brier minus raw | Distinct values |
| --- | --- | --- | --- | --- | ---: |
| Raw `diagnosis_score` | 0.414 (0.310 to 0.510) | 0.308 (0.239 to 0.376) | — | — | 2 |
| Committed calibrator (fitted on `calib_v1`) | 0.600 (0.460 to 0.720) | 0.600 (0.460 to 0.720) | +0.186 (+0.144 to +0.222) | +0.292 (+0.221 to +0.357) | 1 |
| Cross-validated live calibrator | 0.001 (0.004 to 0.086) | 0.061 (0.004 to 0.135) | -0.413 (-0.471 to -0.245) | -0.247 (-0.330 to -0.146) | 6 |

ECE is biased upward on resamples (duplicated cases make bins look less calibrated), so for a predictor whose ECE is near zero the bootstrap interval can sit above the point estimate. The paired differences are the numbers the decision uses.

Other fold splits: repeating the cross-validation with 20 seeds gives a live-calibrator ECE from 0.001 to 0.005 (median 0.003) and Brier from 0.060 to 0.064 (median 0.060).

## Reliability tables

Bins with no cases are left out.

**Raw `diagnosis_score`**

| Bin | Cases | Mean predicted | Accuracy |
| --- | ---: | ---: | ---: |
| 0.7–0.8 | 31 | 0.700 | 0.065 |
| 0.9–1.0 | 19 | 1.000 | 0.947 |

**Committed calibrator (fitted on `calib_v1`)**

| Bin | Cases | Mean predicted | Accuracy |
| --- | ---: | ---: | ---: |
| 0.9–1.0 | 50 | 1.000 | 0.400 |

**Cross-validated live calibrator**

| Bin | Cases | Mean predicted | Accuracy |
| --- | ---: | ---: | ---: |
| 0.0–0.1 | 31 | 0.064 | 0.065 |
| 0.9–1.0 | 19 | 0.948 | 0.947 |

## What the data supports

**The committed calibrator is miscalibrated on real runs.** It was fitted on the synthetic `calib_v1` suite, and on the live runs it maps every case to 1.0 while 40% are correct: ECE 0.600 (0.460 to 0.720) against the raw score's 0.414 (0.310 to 0.510) (a difference of +0.186 (+0.144 to +0.222), worse). So Retrace does not present a calibrated-confidence percentage on real runs; the honest summary of the confidence signal is the observed-accuracy-by-level table above.

Analysis only: a calibrator cross-validated on these live cases would pass the pre-set rule (the cross-validated calibrator counts as clearly better only if the upper end of the 95% paired-bootstrap CI of both (ECE_cv - ECE_raw) and (Brier_cv - Brier_raw) is below 0) — ECE 0.001 (0.004 to 0.086) against 0.414 (0.310 to 0.510). But with 2 distinct raw values it is a two-entry lookup table, not a finer-grained confidence, and it would be fitted on everything we have, leaving nothing held out to report it honestly. **It is not adopted:** the committed calibrator is unchanged and `calibration.json` is not written. Refitting waits for a larger, human-reviewed live set with a held-out split (Future work).

## Limits

- 50 cases from one model and one corpus; a few cases move every number here.
- ECE with 10 equal-width bins is itself noisy at this size; the bootstrap intervals include that noise, and the fold-split range above shows the variation from a different split.
- The labels decide what counts as correct, so any label error moves every number here.
- This report never writes `backend/configs/calibration.json`.
