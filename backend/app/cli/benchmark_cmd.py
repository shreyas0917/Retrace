"""`retrace benchmark report` — held-out benchmark, calibration and classifier comparison.

Produces a JSON report and a Markdown document (docs/benchmarks/heldout_v1.md)
that answer: how accurate is the diagnosis engine per failure class on a
suite it was not developed against, how well calibrated is its confidence,
how often does it defer, and how does it compare with trivial baselines and
an LLM classifier on identical inputs.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.diagnosis.calibration import (
    brier_score,
    expected_calibration_error,
    fit_histogram_calibrator,
    load_calibration,
    reliability_bins,
    save_calibration,
)
from app.services.diagnosis.classifiers import LLMClassifier
from app.services.diagnosis.taxonomy import short_code
from app.services.eval.classifier_bench import (
    compare_classifiers,
    default_classifiers,
    load_cases_from_experiment,
)
from app.services.eval.evaluate import APP_VERSION, run_evaluation


def _scores_and_correct(cases: list[dict[str, Any]], key: str) -> tuple[list[float], list[bool]]:
    scores: list[float] = []
    correct: list[bool] = []
    for c in cases:
        value = c.get(key)
        if value is None:
            continue
        scores.append(float(value))
        correct.append(bool(c.get("correct_failure_code")))
    return scores, correct


def calibration_report(cases: list[dict[str, Any]], n_bins: int = 10) -> dict[str, Any]:
    raw_s, raw_c = _scores_and_correct(cases, "diagnosis_score")
    cal_s, cal_c = _scores_and_correct(cases, "calibrated_confidence")
    raw_bins = reliability_bins(raw_s, raw_c, n_bins) if raw_s else []
    cal_bins = reliability_bins(cal_s, cal_c, n_bins) if cal_s else []
    return {
        "n": len(raw_s),
        "raw": {
            "ece": expected_calibration_error(raw_bins) if raw_bins else None,
            "brier": brier_score(raw_s, raw_c) if raw_s else None,
            "bins": [b.__dict__ for b in raw_bins],
        },
        "calibrated": {
            "ece": expected_calibration_error(cal_bins) if cal_bins else None,
            "brier": brier_score(cal_s, cal_c) if cal_s else None,
            "bins": [b.__dict__ for b in cal_bins],
        },
    }


def run_report(
    db,
    *,
    suite_id: str,
    suite_version: str,
    calibrate_on: str | None,
    calibrate_version: str,
    with_llm: bool,
    classifier_limit: int | None,
    n_bins: int,
    write_calibration: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": APP_VERSION,
        "suite_id": suite_id,
        "suite_version": suite_version,
    }

    # 1. Fit a calibrator on a disjoint suite. It is only written to the
    #    committed config with an explicit write_calibration; otherwise the
    #    fit is reported for comparison and the committed calibrator applies.
    if calibrate_on:
        calib = run_evaluation(db, suite_id=calibrate_on, suite_version=calibrate_version, persist=True)
        scores, correct = _scores_and_correct(calib["cases"], "diagnosis_score")
        table = fit_histogram_calibrator(
            scores,
            correct,
            n_bins=n_bins,
            fitted_on=f"{calibrate_on}@{calibrate_version} ({calib['suite_hash']})",
            notes={"experiment_id": calib["experiment_id"]},
        )
        path = save_calibration(table) if write_calibration else None
        report["calibration_fit"] = {
            "written": bool(write_calibration),
            "suite": calibrate_on,
            "suite_hash": calib["suite_hash"],
            "experiment_id": calib["experiment_id"],
            "sample_size": table.sample_size,
            "ece_before": table.ece_before,
            "brier_before": table.brier_before,
            "path": str(path) if path else None,
            "summary": {k: v for k, v in calib["summary"].items() if k not in {"confusion_matrix", "per_class"}},
        }

    # 2. Evaluation, using whichever calibrator is on disk now.
    applied = load_calibration()
    report["applied_calibrator"] = (
        {"fitted_on": applied.fitted_on, "created_at": applied.created_at, "sample_size": applied.sample_size}
        if applied
        else None
    )
    result = run_evaluation(db, suite_id=suite_id, suite_version=suite_version, persist=True)
    cases = result["cases"]
    report.update(
        {
            "experiment_id": result["experiment_id"],
            "suite_hash": result["suite_hash"],
            "git_commit": result.get("git_commit"),
            "summary": result["summary"],
            "gate": {
                "status": result["gate_status"],
                "exit_code": result["exit_code"],
                "thresholds": result["thresholds"],
                "comparison": result["comparison"],
            },
            "calibration": calibration_report(cases, n_bins=n_bins),
            "calibration_table": (load_calibration().to_dict() if load_calibration() else None),
            "misclassified": [
                {
                    "case_id": c["case_id"],
                    "expected": c["expected_failure_code"],
                    "predicted": c["predicted_failure_code"],
                    "rule_id": c["predicted_rule_id"],
                    "score": c.get("diagnosis_score"),
                    "calibrated_confidence": c.get("calibrated_confidence"),
                    "uncertain": c.get("uncertain"),
                    "tags": c.get("tags"),
                    "explanation": c.get("explanation"),
                }
                for c in cases
                if not c.get("correct_failure_code")
            ],
            "label_distribution": _label_distribution(cases),
        }
    )

    # 3. Classifier comparison on identical signal bags.
    bench_cases = load_cases_from_experiment(db, result["experiment_id"])
    if classifier_limit:
        bench_cases = bench_cases[:classifier_limit]
    labels = [c["expected_failure_code"] for c in bench_cases]
    classifiers = default_classifiers(labels)
    llm_meta: dict[str, Any] | None = None
    if with_llm:
        llm = LLMClassifier()
        classifiers.append(llm)
        llm_meta = {"model": llm.model, "prompt_version": llm.prompt_version, "temperature": 0.0}
    comparison = compare_classifiers(bench_cases, classifiers)
    comparison.pop("per_case", None)
    report["classifier_comparison"] = {**comparison, "llm": llm_meta, "n_cases": len(bench_cases)}
    return report


def _label_distribution(cases: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in cases:
        out[c["expected_failure_code"]] = out.get(c["expected_failure_code"], 0) + 1
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------
def _pct(v: Any) -> str:
    return "n/a" if v is None else f"{float(v) * 100:.1f}%"


def _f(v: Any, nd: int = 3) -> str:
    return "n/a" if v is None else f"{float(v):.{nd}f}"


def render_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines: list[str] = []
    lines.append(f"# Held-out diagnosis benchmark: `{report['suite_id']}@{report['suite_version']}`")
    lines.append("")
    lines.append(
        f"Generated {report['generated_at'][:19]}Z by `retrace benchmark report` · app {report['app_version']}"
        + (f" · commit `{report['git_commit'][:12]}`" if report.get("git_commit") else "")
    )
    lines.append("")
    lines.append(
        "This suite was generated independently of the rule engine (labels come from scenario "
        "semantics, see `scripts/build_heldout_suite.py`) and is never used to tune rules or "
        "thresholds. Roughly 15% of cases sit on decision boundaries on purpose. Fixtures are "
        "synthetic with scripted judge outputs: the numbers measure the **diagnosis engine**, "
        "not live-LLM robustness."
    )
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Cases | {s['total_cases']} |")
    lines.append(f"| Suite hash | `{report['suite_hash']}` |")
    lines.append(f"| Accuracy (lenient: predicted ∈ acceptable codes) | {_pct(s['failure_code_accuracy'])} |")
    lines.append(f"| Accuracy (strict: predicted == label) | {_pct(s.get('strict_accuracy'))} |")
    lines.append(f"| Rule-id accuracy | {_pct(s.get('rule_accuracy'))} |")
    lines.append(f"| Evidence accuracy | {_pct(s.get('evidence_accuracy'))} |")
    lines.append(f"| Macro-F1 | {_f(s.get('macro_f1'))} |")
    lines.append(f"| Micro-F1 | {_f(s.get('micro_f1'))} |")
    lines.append(f"| Weighted-F1 | {_f(s.get('weighted_f1'))} |")
    sel = s.get("selective") or {}
    lines.append(f"| Uncertain (deferred) rate | {_pct(sel.get('uncertain_rate'))} |")
    lines.append(
        f"| Selective accuracy (answered cases only) | {_pct(sel.get('selective_accuracy'))} at {_pct(sel.get('coverage'))} coverage |"
    )
    lines.append(f"| Gate | {report['gate']['status']} (exit {report['gate']['exit_code']}) |")
    lines.append("")

    lines.append("## Per-class precision / recall / F1")
    lines.append("")
    lines.append("| Expected label | Support | Precision | Recall | F1 | FP | FN |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for label, m in sorted((s.get("per_class") or {}).items()):
        lines.append(
            f"| `{label}` | {m['support']} | {_f(m['precision'])} | {_f(m['recall'])} | {_f(m['f1'])} | {m['fp']} | {m['fn']} |"
        )
    lines.append("")

    cm = s.get("confusion_matrix") or {}
    labels = cm.get("labels") or []
    if labels:
        lines.append("## Confusion matrix (rows = expected, columns = predicted)")
        lines.append("")
        short = {lbl: _abbrev(lbl) for lbl in labels}
        lines.append("| | " + " | ".join(short[l] for l in labels) + " |")
        lines.append("| --- | " + " | ".join("---:" for _ in labels) + " |")
        for a in labels:
            row = cm["matrix"].get(a, {})
            lines.append(f"| {short[a]} | " + " | ".join(str(row.get(p, 0)) for p in labels) + " |")
        lines.append("")
        lines.append("Abbreviations: " + ", ".join(f"{short[l]} = `{l}`" for l in labels))
        lines.append("")

    cal = report.get("calibration") or {}
    lines.append("## Confidence calibration")
    lines.append("")
    fit = report.get("calibration_fit")
    applied = report.get("applied_calibrator")
    if fit and fit.get("written"):
        lines.append(
            f"Calibrator: histogram binning fitted on `{fit['suite']}` ({fit['sample_size']} cases, "
            f"disjoint from this suite), written to `backend/configs/calibration.json` and applied below."
        )
    else:
        if applied:
            lines.append(
                f"Calibrated confidence below uses the committed calibrator in "
                f"`backend/configs/calibration.json`, fitted on {applied['fitted_on']} "
                f"({applied['sample_size']} cases)."
            )
        else:
            lines.append("No calibrator is committed, so calibrated confidence equals the raw score.")
        if fit:
            lines.append(
                f"A fresh fit on `{fit['suite']}` was computed for comparison but not written; "
                f"pass `--write-calibration` to replace the committed calibrator."
            )
    lines.append("")
    lines.append("| | Raw rule score | Calibrated confidence |")
    lines.append("| --- | ---: | ---: |")
    lines.append(
        f"| Expected calibration error (lower is better) | {_f(cal.get('raw', {}).get('ece'))} | {_f(cal.get('calibrated', {}).get('ece'))} |"
    )
    lines.append(
        f"| Brier score (lower is better) | {_f(cal.get('raw', {}).get('brier'))} | {_f(cal.get('calibrated', {}).get('brier'))} |"
    )
    lines.append("")
    lines.append("Reliability bins on this suite (calibrated confidence):")
    lines.append("")
    lines.append("| Bin | Count | Mean confidence | Empirical accuracy |")
    lines.append("| --- | ---: | ---: | ---: |")
    for b in cal.get("calibrated", {}).get("bins", []):
        if b["count"] == 0:
            continue
        lines.append(f"| {b['lo']:.1f}–{b['hi']:.1f} | {b['count']} | {_f(b['mean_score'])} | {_f(b['accuracy'])} |")
    lines.append("")

    cc = report.get("classifier_comparison") or {}
    clf = cc.get("classifiers") or {}
    lines.append("## Classifier comparison on identical signal bags")
    lines.append("")
    lines.append(
        "Every classifier receives the exact signal bag the rule engine saw (retrieval counts, gold hit, "
        "judge verdicts). `majority` predicts the most common label; `heuristic` uses four cheap "
        "non-judge branches; `llm` prompts the configured model with the signals and the taxonomy."
    )
    lines.append("")
    lines.append(
        "| Classifier | Lenient acc. | Strict acc. | Macro-F1 | Weighted-F1 | Uncertain rate | Malformed | Mean latency |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name, m in clf.items():
        lines.append(
            f"| `{name}` | {_pct(m['lenient_accuracy'])} | {_pct(m['strict_accuracy'])} | {_f(m['macro_f1'])} | "
            f"{_f(m['weighted_f1'])} | {_pct(m['uncertain_rate'])} | {m['malformed_outputs']} | {_f(m['mean_latency_ms'], 1)} ms |"
        )
    lines.append("")
    if cc.get("llm"):
        lines.append(
            f"LLM classifier: model `{cc['llm']['model']}`, prompt `{cc['llm']['prompt_version']}`, temperature 0."
        )
    else:
        lines.append("LLM classifier not run in this report (requires a live model; run with `--with-llm`).")
    lines.append("")
    agree = cc.get("agreement") or {}
    if agree:
        lines.append("| Pair | Raw agreement | Cohen's kappa |")
        lines.append("| --- | ---: | ---: |")
        for pair, m in agree.items():
            lines.append(f"| `{pair}` | {_pct(m['raw_agreement'])} | {_f(m['cohens_kappa'])} |")
        lines.append("")
    if cc.get("rule_engine_replay_consistency") is not None:
        lines.append(
            f"Rule-engine replay consistency (re-applying rules to stored signals reproduces the stored "
            f"decision): {_pct(cc['rule_engine_replay_consistency'])}."
        )
        lines.append("")

    mis = report.get("misclassified") or []
    lines.append(f"## Misclassified cases ({len(mis)})")
    lines.append("")
    if not mis:
        lines.append("None.")
    else:
        lines.append("| Case | Expected | Predicted | Rule | Calibrated conf. | Deferred | Tags |")
        lines.append("| --- | --- | --- | --- | ---: | --- | --- |")
        for m in mis:
            lines.append(
                f"| {m['case_id']} | `{m['expected']}` | `{m['predicted']}` | {m['rule_id']} | "
                f"{_f(m.get('calibrated_confidence'), 2)} | {'yes' if m.get('uncertain') else 'no'} | "
                f"{', '.join(t for t in (m.get('tags') or []) if t not in {'heldout'})} |"
            )
        lines.append("")
        lines.append("Example explanations produced by the engine for misclassified cases:")
        lines.append("")
        for m in mis[:5]:
            if m.get("explanation"):
                lines.append(f"- **{m['case_id']}**: {m['explanation']}")
        lines.append("")

    lines.append("## Label distribution")
    lines.append("")
    lines.append("| Label | Cases |")
    lines.append("| --- | ---: |")
    for label, n in (report.get("label_distribution") or {}).items():
        lines.append(f"| `{label}` | {n} |")
    lines.append("")
    lines.append("## How to reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/build_heldout_suite.py --check")
    lines.append(
        "docker compose exec backend python -m app.cli.retrace benchmark report "
        "--suite heldout_v1 --calibrate-on calib_v1 --markdown /docs/benchmarks/heldout_v1.md"
    )
    lines.append("# add --with-llm to include the LLM classifier (needs MODEL_* configured)")
    lines.append("# add --write-calibration to refit and replace backend/configs/calibration.json")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _abbrev(label: str) -> str:
    return short_code(label)


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------
HELDOUT_DEFAULT_OUT = "/data/reports/heldout_report.json"


def cmd_live_report(args: argparse.Namespace) -> int:
    """live_* suites: real runs with blind labels (services/eval/live_report.py)."""
    from app.db import session as db_session
    from app.services.eval.live_report import render_live_markdown, run_live_report

    db_session.init_db()
    assert db_session.SessionLocal is not None
    db = db_session.SessionLocal()
    try:
        report = run_live_report(db, suite_id=args.suite, suite_version=args.suite_version)
    except Exception as exc:  # noqa: BLE001
        print(f"Benchmark error: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()
    out = args.out if args.out and args.out != HELDOUT_DEFAULT_OUT else f"/data/reports/{args.suite}_report.json"
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    if args.markdown:
        md = Path(args.markdown)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_live_markdown(report), encoding="utf-8")
        print(f"wrote {md}")
    s, ci = report["summary"], report["confidence_intervals"]
    print(
        f"{report['suite_id']}: lenient {s['failure_code_accuracy']:.3f} "
        f"[{ci['lenient_accuracy']['low']}, {ci['lenient_accuracy']['high']}] strict {s['strict_accuracy']:.3f} "
        f"macro_f1 {s['macro_f1']} uncertain_rate {s['selective']['uncertain_rate']} misses {len(report['misses'])}"
    )
    return 0


def cmd_benchmark_report(args: argparse.Namespace) -> int:
    if str(args.suite).startswith("live_"):
        return cmd_live_report(args)

    from app.db import session as db_session

    db_session.init_db()
    assert db_session.SessionLocal is not None
    db = db_session.SessionLocal()
    try:
        report = run_report(
            db,
            suite_id=args.suite,
            suite_version=args.suite_version,
            calibrate_on=args.calibrate_on,
            calibrate_version=args.calibrate_version,
            with_llm=bool(args.with_llm),
            classifier_limit=args.classifier_limit,
            n_bins=args.bins,
            write_calibration=bool(getattr(args, "write_calibration", False)),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Benchmark error: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()
        try:
            from app.core.telemetry import flush_telemetry

            flush_telemetry()
        except Exception:  # noqa: BLE001 — telemetry must never fail a benchmark
            pass

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    if args.markdown:
        md = Path(args.markdown)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_markdown(report), encoding="utf-8")
        print(f"wrote {md}")

    s = report["summary"]
    print(
        f"{report['suite_id']}: lenient {s['failure_code_accuracy']:.3f} strict {s['strict_accuracy']:.3f} "
        f"macro_f1 {s['macro_f1']} uncertain_rate {s['selective']['uncertain_rate']} "
        f"gate {report['gate']['status']}"
    )
    return 0


def cmd_calibration_cv(args: argparse.Namespace) -> int:
    """k-fold calibration on a labelled suite; never writes the calibration config."""
    from app.db import session as db_session
    from app.services.eval.calibration_cv import cross_validated_calibration, render_cv_markdown, score_distribution
    from app.services.eval.live_report import AI_BLIND_WORDING, label_provenance
    from app.services.eval.suite_loader import suite_dir

    db_session.init_db()
    assert db_session.SessionLocal is not None
    db = db_session.SessionLocal()
    try:
        result = run_evaluation(db, suite_id=args.suite, suite_version=args.suite_version, persist=False)
    except Exception as exc:  # noqa: BLE001
        print(f"Calibration error: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()
    rows = result["cases"]

    if args.distribution_only:
        dist = score_distribution(rows, n_bins=args.bins)
        print(json.dumps({"suite": args.suite, "suite_hash": result["suite_hash"], **dist}, indent=2))
        return 0

    report = cross_validated_calibration(rows, k=args.folds, n_bins=args.bins)
    report.update({"suite_id": args.suite, "suite_hash": result["suite_hash"], "git_commit": result.get("git_commit")})
    manifest_path = suite_dir(args.suite, args.suite_version) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    provenance = label_provenance(
        {
            "annotator": manifest.get("annotator"),
            "review": manifest.get("review"),
            "summary": {"total_cases": len(rows)},
        }
    )
    banner = f"Labels: {AI_BLIND_WORDING}" if manifest.get("annotator") == "ai_draft_blind" else None
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    if args.markdown:
        command = (
            f"retrace benchmark calibration-cv --suite {args.suite} --folds {args.folds} --bins {args.bins} "
            f"--markdown {args.markdown}"
        )
        prov = f"Suite hash `{result['suite_hash']}`, commit {result.get('git_commit') or 'unknown'}. {provenance}"
        md = Path(args.markdown)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(
            render_cv_markdown(
                report,
                command=command,
                suite=args.suite,
                provenance=prov,
                banner=banner,
            ),
            encoding="utf-8",
        )
        print(f"wrote {md}")
    p = report["predictors"]
    for name in ("raw", "calib_v1", "cv_live"):
        print(f"{name:<9} ece {p[name]['ece']} brier {p[name]['brier']}")
    print(
        f"distinct raw scores {report['distinct_raw_scores']}; clearly better: {report['decision']['cv_clearly_lower_than_raw']}"
    )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    bench = sub.add_parser("benchmark", help="Benchmark reports (held-out suite, calibration, classifiers)")
    bench_sub = bench.add_subparsers(dest="benchmark_command", required=True)
    rep = bench_sub.add_parser("report", help="Run a suite and write a full benchmark report")
    rep.add_argument("--suite", default="heldout_v1")
    rep.add_argument("--suite-version", default="1.0.0")
    rep.add_argument("--calibrate-on", default="calib_v1", help="Suite used to fit the calibrator ('' to skip)")
    rep.add_argument("--calibrate-version", default="1.0.0")
    rep.add_argument("--with-llm", action="store_true", help="Also run the LLM classifier (live model)")
    rep.add_argument("--classifier-limit", type=int, default=None)
    rep.add_argument("--bins", type=int, default=10)
    rep.add_argument("--out", default="/data/reports/heldout_report.json")
    rep.add_argument("--markdown", default=None)
    rep.add_argument(
        "--write-calibration",
        action="store_true",
        help="Write the calibrator fitted on --calibrate-on to backend/configs/calibration.json",
    )
    rep.set_defaults(func=cmd_benchmark_report)
    cv = bench_sub.add_parser(
        "calibration-cv",
        help="k-fold calibration on a labelled suite (never writes the calibration config)",
    )
    cv.add_argument("--suite", default="live_v1")
    cv.add_argument("--suite-version", default="1.0.0")
    cv.add_argument("--folds", type=int, default=5)
    cv.add_argument("--bins", type=int, default=10)
    cv.add_argument("--out", default=None)
    cv.add_argument("--markdown", default=None)
    cv.add_argument(
        "--distribution-only",
        action="store_true",
        help="Only print how the suite's raw and calibrated scores spread over the bins",
    )
    cv.set_defaults(func=cmd_calibration_cv)


def main(argv: list[str] | None = None) -> int:
    """Standalone entry: `python -m app.cli.benchmark_cmd report ...`."""
    parser = argparse.ArgumentParser(prog="retrace benchmark")
    sub = parser.add_subparsers(dest="benchmark_command", required=True)
    rep = sub.add_parser("report")
    rep.add_argument("--suite", default="heldout_v1")
    rep.add_argument("--suite-version", default="1.0.0")
    rep.add_argument("--calibrate-on", default="calib_v1")
    rep.add_argument("--calibrate-version", default="1.0.0")
    rep.add_argument("--with-llm", action="store_true")
    rep.add_argument("--classifier-limit", type=int, default=None)
    rep.add_argument("--bins", type=int, default=10)
    rep.add_argument("--out", default="/data/reports/heldout_report.json")
    rep.add_argument("--markdown", default=None)
    rep.add_argument(
        "--write-calibration",
        action="store_true",
        help="Write the calibrator fitted on --calibrate-on to backend/configs/calibration.json",
    )
    rep.set_defaults(func=cmd_benchmark_report)
    args = parser.parse_args(argv)
    if args.calibrate_on == "":
        args.calibrate_on = None
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
