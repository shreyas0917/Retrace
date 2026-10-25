"""Compare experiment metrics to baseline + absolute thresholds."""

from __future__ import annotations

from typing import Any


METRIC_KEYS = (
    "failure_code_accuracy",
    "rule_accuracy",
    "evidence_accuracy",
)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compare_metrics(
    *,
    current: dict[str, Any],
    baseline: dict[str, Any] | None,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Return comparison table + pass/fail. Regression ≠ infrastructure failure."""
    rows: list[dict[str, Any]] = []
    violations: list[str] = []

    total = int(current.get("total_cases") or 0)
    incorrect = int(current.get("incorrect") or 0)
    error_rate = (incorrect / total) if total > 0 else 0.0
    max_err = float(thresholds.get("fail_on_eval_error_rate_gt", 0.02))
    if total > 0 and error_rate > max_err:
        violations.append(
            f"eval_error_rate {error_rate:.4f} > {max_err:.4f}"
        )

    drop_map = {
        "failure_code_accuracy": "require_failure_code_accuracy_drop_lt",
        "rule_accuracy": "require_rule_accuracy_drop_lt",
        "evidence_accuracy": "require_evidence_accuracy_drop_lt",
    }
    min_map = {
        "failure_code_accuracy": "min_failure_code_accuracy",
        "rule_accuracy": "min_rule_accuracy",
        "evidence_accuracy": "min_evidence_accuracy",
    }

    for key in METRIC_KEYS:
        cur = _num(current.get(key))
        base = _num(baseline.get(key)) if baseline else None
        drop_lt = float(thresholds.get(drop_map[key], 0.05))
        min_floor = float(thresholds.get(min_map[key], 0.0))

        status = "PASS"
        delta: float | None = None
        if cur is None:
            status = "N/A"
        else:
            if cur < min_floor:
                status = "FAIL"
                violations.append(f"{key}={cur:.4f} < min {min_floor:.4f}")
            if base is not None:
                delta = cur - base
                # Regression when accuracy drops by >= drop_lt
                if (base - cur) >= drop_lt - 1e-12:
                    status = "FAIL"
                    violations.append(
                        f"{key} drop {base - cur:.4f} >= {drop_lt:.4f}"
                    )
                elif status != "FAIL":
                    if abs(delta) < 1e-12:
                        status = "UNCHANGED"
                    elif delta > 0:
                        status = "IMPROVED"
                    else:
                        status = "PASS"  # small drop within tolerance

        rows.append(
            {
                "metric": key,
                "baseline": base,
                "current": cur,
                "delta": delta,
                "status": status,
            }
        )

    passed = len(violations) == 0
    return {
        "passed": passed,
        "violations": violations,
        "rows": rows,
        "error_rate": error_rate,
        "has_baseline": baseline is not None,
    }
