"""Phase 6 evaluate orchestration: run suite → gate → exit semantics."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import Experiment
from app.services.eval.baseline import get_active_baseline
from app.services.eval.regression import compare_metrics
from app.services.eval.runner import run_suite_benchmark
from app.services.eval.suite_loader import load_suite
from app.services.eval.thresholds_config import load_thresholds


APP_VERSION = "0.9.0"

# Exit codes (PRD §16)
EXIT_PASS = 0
EXIT_REGRESSION = 1
EXIT_ERROR = 2


class EvalIntegrityError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="SUITE_INTEGRITY_ERROR",
            message=message,
            status_code=400,
            details=details or {},
        )


def detect_git_commit() -> str | None:
    """Best-effort git SHA; None if unavailable (never invent one)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            return sha or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def verify_suite_integrity(
    suite_id: str,
    suite_version: str,
    *,
    expect_hash: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Load suite and optionally enforce expect_hash. Raises on mismatch."""
    cases, suite_hash, meta = load_suite(suite_id, suite_version)
    if expect_hash and expect_hash != suite_hash:
        raise EvalIntegrityError(
            "suite integrity error: expected hash does not match actual",
            {"expected": expect_hash, "actual": suite_hash},
        )
    return suite_hash, {
        "case_count": len(cases),
        "suite_hash": suite_hash,
        "meta": meta,
    }


def run_evaluation(
    db: Session,
    *,
    suite_id: str,
    suite_version: str = "1.0.0",
    expect_hash: str | None = None,
    thresholds_path: str | Path | None = None,
    settings: Settings | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """
    Run suite evaluation, persist experiment, compare to active baseline.

    Returns a result dict including exit_code (0/1/2 semantics for the caller).
    Infrastructure errors are raised (caller maps to exit 2).
    """
    settings = settings or get_settings()
    thresholds = load_thresholds(thresholds_path)

    suite_hash, _ = verify_suite_integrity(
        suite_id, suite_version, expect_hash=expect_hash
    )

    git_commit = detect_git_commit()
    report = run_suite_benchmark(
        db,
        suite_id=suite_id,
        suite_version=suite_version,
        settings=settings,
        persist=persist,
    )

    # Enrich experiment reproducibility metadata
    if persist:
        exp = db.get(Experiment, report["experiment_id"])
        if exp:
            pipeline = dict(exp.pipeline or {})
            pipeline.update(
                {
                    "app_version": APP_VERSION,
                    "git_commit": git_commit,
                    "acceptance_thresholds_version": thresholds.get("version"),
                    "acceptance_thresholds": {
                        k: v
                        for k, v in thresholds.items()
                        if not str(k).startswith("_")
                    },
                    "cost_per_query": None,  # unavailable — never invent
                    "prompt_versions": {
                        "generator": "generator.v1",
                        "relevance": "relevance.v1",
                        "faithfulness": "faithfulness.v1",
                        "contradiction": "contradiction.v1",
                    },
                }
            )
            exp.pipeline = pipeline
            exp.git_commit = git_commit
            db.commit()
            report["pipeline"] = pipeline
            report["git_commit"] = git_commit

    summary = report["summary"]
    baseline_row = get_active_baseline(
        db, suite_id=suite_id, suite_version=suite_version
    )
    baseline_metrics = baseline_row.metrics if baseline_row else None
    comparison = compare_metrics(
        current=summary,
        baseline=baseline_metrics,
        thresholds=thresholds,
    )

    exit_code = EXIT_PASS if comparison["passed"] else EXIT_REGRESSION
    status = "COMPLETED" if comparison["passed"] else "REGRESSION"

    if persist:
        exp = db.get(Experiment, report["experiment_id"])
        if exp and exp.status == "COMPLETED":
            # Only downgrade COMPLETED → REGRESSION when gate fails
            if not comparison["passed"]:
                exp.status = "REGRESSION"
            db.commit()
        elif exp and comparison["passed"]:
            exp.status = "COMPLETED"
            db.commit()

    result = {
        **report,
        "app_version": APP_VERSION,
        "git_commit": git_commit,
        "suite_hash": suite_hash,
        "thresholds": {
            k: v for k, v in thresholds.items() if not str(k).startswith("_")
        },
        "baseline": (
            {
                "baseline_id": baseline_row.id,
                "experiment_id": baseline_row.experiment_id,
                "name": baseline_row.name,
                "metrics": baseline_row.metrics,
            }
            if baseline_row
            else None
        ),
        "comparison": comparison,
        "gate_status": "PASS" if comparison["passed"] else "REGRESSION",
        "exit_code": exit_code,
        "no_baseline": baseline_row is None,
    }
    return result


def format_eval_report(result: dict[str, Any]) -> str:
    """Compact engineer-facing terminal report."""
    summary = result["summary"]
    lines = [
        "Retrace Evaluation",
        "────────────────────────────────────",
        f"Suite: {result['suite_id']} @ {result['suite_version']}",
        f"Hash: {result['suite_hash']}",
        f"Experiment: {result['experiment_id']}",
        "",
        "Cases",
        f"  Total:       {summary['total_cases']}",
        f"  Correct:     {summary['correct']}",
        f"  Incorrect:   {summary['incorrect']}",
        "",
        "Metrics",
    ]

    comparison = result.get("comparison") or {}
    for row in comparison.get("rows") or []:
        cur = row["current"]
        cur_s = "n/a" if cur is None else f"{cur:.3f}"
        lines.append(
            f"  {row['metric']:<26} {cur_s:>6}   {row['status']}"
        )

    lines.append("")
    if result.get("no_baseline"):
        lines.append("Baseline")
        lines.append("  No accepted baseline found.")
        lines.append("  Experiment completed.")
        lines.append("  Baseline promotion requires an explicit command:")
        lines.append(
            f"    retrace baseline promote {result['experiment_id']}"
        )
    else:
        base = result["baseline"]
        lines.append("Baseline")
        lines.append(f"  baseline: {base['baseline_id']}")
        lines.append(f"  status:   {result['gate_status']}")
        lines.append("")
        lines.append(
            f"{'Metric':<26} {'Baseline':>10} {'Current':>10} {'Delta':>10} {'Status':>10}"
        )
        lines.append("─" * 70)
        for row in comparison.get("rows") or []:
            b = "—" if row["baseline"] is None else f"{row['baseline']:.3f}"
            c = "—" if row["current"] is None else f"{row['current']:.3f}"
            d = "—" if row["delta"] is None else f"{row['delta']:+.3f}"
            lines.append(
                f"{row['metric']:<26} {b:>10} {c:>10} {d:>10} {row['status']:>10}"
            )

    failing = [c for c in result.get("cases") or [] if not c.get("correct")]
    if failing:
        lines.append("")
        lines.append("Failing cases")
        for c in failing:
            lines.append(
                f"  {c['case_id']}: expected={c['expected']['failure_code']} "
                f"predicted={c['predicted']['failure_code']} "
                f"rule={c['predicted']['rule_id']}"
            )

    if comparison.get("violations"):
        lines.append("")
        lines.append("Violations")
        for v in comparison["violations"]:
            lines.append(f"  - {v}")

    lines.append("")
    lines.append(f"Result: {result['gate_status']}")
    lines.append(f"Exit code: {result['exit_code']}")
    return "\n".join(lines)
