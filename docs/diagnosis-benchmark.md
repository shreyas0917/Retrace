# Diagnosis benchmark method

This document explains how Retrace measures the diagnosis engine in v1.0 and
what the numbers in [benchmarks/heldout_v1.md](benchmarks/heldout_v1.md) do and
do not mean. The planted suite (12 scenarios) proves the engine is wired
correctly; the held-out suite estimates per-class quality, confidence
calibration and how the rule engine compares with other classifiers.

## Suites

| Suite | Cases | Purpose | Used for tuning? |
| --- | ---: | --- | --- |
| `planted_v1` | 12 | One unambiguous scenario per failure class; CI smoke gate | Rules were written against these semantics |
| `calib_v1` | 80 | Fit the confidence calibrator | Only for calibration, never for rules |
| `heldout_v1` | 160 | Per-class precision/recall/F1, calibration check, classifier comparison | Never |
| `gold_v1` | 2 | Hand-written offline executions | No |

`heldout_v1` and `calib_v1` are produced by `scripts/build_heldout_suite.py`
from a bank of 26 policy facts across 13 documents and 12 scenario templates
(one per failure class plus infrastructure failures). Each case is an offline
execution fixture: retrieved chunks with ranks and scores, the answer, and
scripted judge outputs. Seeds differ per suite, case ids are disjoint, and
the suite hash is pinned in each `manifest.json`.

Labels come from scenario semantics, for example "the gold chunk exists but
was not retrieved" or "the answer mixes one supported and one invented claim",
not from the rule code. About 15% of cases are deliberately placed on decision
boundaries (faithfulness between 0.80 and 0.84, two of three chunks
irrelevant, relevance scores between 0.5 and 0.6). Where two codes are
genuinely defensible the case lists both in `acceptable_primary_codes` and the
report shows strict accuracy (exact label) next to lenient accuracy.

Honest framing: the fixtures are synthetic and the judge outputs are scripted.
The benchmark measures the deterministic diagnosis engine given judge
verdicts; it does not measure how good the LLM judges are on real text. Judge
quality is measured separately in
[benchmarks/judge_validation.md](benchmarks/judge_validation.md).

## What is reported

- Lenient and strict accuracy, rule-id accuracy, evidence accuracy.
- Per-class precision, recall, F1 and support, plus macro, micro and
  support-weighted F1 and a confusion matrix.
- Deferral: the engine now emits `DIAGNOSIS_UNCERTAIN` (rule R90) when judge
  outputs are self-inconsistent, and flags any decision whose calibrated
  confidence is below 0.5 as `uncertain`. The report shows coverage, selective
  accuracy on answered cases and how many deferred cases would have been right.
- Calibration: expected calibration error and Brier score for the raw rule
  score and for the calibrated confidence, plus reliability bins.
- Classifier comparison on identical signal bags.

## Confidence calibration

The rule engine's `diagnosis_score` is a heuristic strength value. A histogram
binning calibrator (`app/services/diagnosis/calibration.py`) maps that score
to the empirical accuracy observed in its bin on `calib_v1`. The table is
stored in `backend/configs/calibration.json` and applied at diagnosis time;
`calibrated_confidence` and `calibration_version` are persisted with every
diagnosis and shown in the console. Bins with no calibration observations
fall back to the raw score rather than inventing a probability.

## Classifier comparison

`app/services/diagnosis/classifiers.py` defines four classifiers over the same
`SignalBag`:

| Classifier | Inputs | Role |
| --- | --- | --- |
| `rule_engine` | Full signal bag | Production reference |
| `majority` | None (most frequent label in the suite) | Chance-level floor |
| `heuristic` | Timeout, malformed judge, empty retrieval, gold hit, abstention | Cheap baseline without judges |
| `llm` | Signal bag rendered as JSON plus the taxonomy | LLM-as-classifier, structured JSON output, one retry, malformed output maps to `DIAGNOSIS_UNCERTAIN` |

The comparison runs after the suite so every classifier reads the exact
signals the engine persisted. It reports accuracy and F1 per classifier,
pairwise Cohen's kappa, and a replay-consistency check that re-applying the
rules to stored signals reproduces the stored decision.

Prompt iteration, recorded for honesty: the first LLM classifier prompt
(`classifier.v1`) handed the model the raw signal JSON and the taxonomy list.
With `llama3.2:latest` (3B, temperature 0) it collapsed to `RETRIEVAL_MISS`
for 113 of 160 cases, including cases with no gold labels, and scored 8.8%.
`classifier.v2` renders the signals as plain facts ("Gold labels are NOT
available", "Relevance judge: 1/4 chunks relevant, 75% irrelevant; context
sufficient: no") and adds an ordered decision guide. The same model then
scores 40.6% lenient accuracy and macro-F1 0.42, perfect on timeouts,
malformed judges, empty retrieval and contradiction, and weak on the
abstention and grounding distinctions. The committed report uses v2. A
stronger model will do better; run `retrace benchmark report --with-llm` with
`MODEL_NAME` set to compare, and keep in mind the LLM classifier costs about
nine seconds per case on this machine against 0.3 ms for the rules.

## Explanations

Every diagnosis now carries an `explanation` string built by
`app/services/diagnosis/explain.py` from the signals and the matched rule,
for example: "Retrieved 4 chunk(s); gold-relevant chunk(s) present; relevance
judge marked 1/4 chunk(s) relevant (75% irrelevant) and judged the context
sufficient; the system answered; faithfulness 0.82 with 4 supported / 0
unsupported claim(s) (within 0.05 of the 0.85 threshold) ... Rule R90
therefore classifies this as DIAGNOSIS_UNCERTAIN." It is templated, not
generated by a model, so it can be reproduced from stored signals.

## Reproduce

```bash
python scripts/build_heldout_suite.py --check
docker compose exec backend python -m app.cli.retrace benchmark report \
  --suite heldout_v1 --calibrate-on calib_v1 \
  --markdown /docs/benchmarks/heldout_v1.md --out /data/reports/heldout_report.json
# add --with-llm to include the LLM classifier (uses MODEL_* from .env)
```

The held-out run is also a test: `backend/tests/test_v1_diagnosis_benchmark.py`
runs the full suite and fails if lenient accuracy drops below the 80% floor
in `backend/configs/thresholds.heldout_v1.yaml` or if any non-boundary case
is misclassified.
