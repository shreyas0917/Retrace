"""Load acceptance thresholds for experiment gating (PRD §16)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.errors import AppError


class ThresholdConfigError(AppError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            code="THRESHOLD_CONFIG_ERROR",
            message=message,
            status_code=400,
            details=details or {},
        )


DEFAULT_THRESHOLDS: dict[str, Any] = {
    "version": "acceptance_thresholds.v1",
    "require_failure_code_accuracy_drop_lt": 0.05,
    "require_rule_accuracy_drop_lt": 0.05,
    "require_evidence_accuracy_drop_lt": 0.05,
    "min_failure_code_accuracy": 0.0,
    "min_rule_accuracy": 0.0,
    "min_evidence_accuracy": 0.0,
    "fail_on_eval_error_rate_gt": 0.02,
}


def _configs_dir() -> Path:
    # backend/app/services/eval/thresholds_config.py → backend/configs/
    here = Path(__file__).resolve()
    return here.parents[3] / "configs"


def default_thresholds_path(suite_id: str | None = None) -> Path:
    """Per-suite file `thresholds.<suite_id>.yaml` when present, else default.

    Large held-out suites legitimately have a non-zero error rate, so they
    carry their own acceptance thresholds instead of the planted-suite
    defaults (which demand near-perfect accuracy).
    """
    configs = _configs_dir()
    if suite_id:
        safe = "".join(ch for ch in suite_id if ch.isalnum() or ch in "._-")
        per_suite = configs / f"thresholds.{safe}.yaml"
        if per_suite.is_file():
            return per_suite
    return configs / "thresholds.default.yaml"


def load_thresholds(
    path: str | Path | None = None, *, suite_id: str | None = None
) -> dict[str, Any]:
    """Load YAML thresholds; missing default file falls back to DEFAULT_THRESHOLDS."""
    if path is None:
        path = default_thresholds_path(suite_id)
    path = Path(path)
    if not path.is_file():
        if path == default_thresholds_path():
            return dict(DEFAULT_THRESHOLDS)
        raise ThresholdConfigError(
            f"thresholds file not found: {path}",
            {"path": str(path)},
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ThresholdConfigError(
            f"invalid thresholds YAML: {exc}",
            {"path": str(path)},
        ) from exc
    if not isinstance(raw, dict):
        raise ThresholdConfigError("thresholds file must be a mapping")
    merged = dict(DEFAULT_THRESHOLDS)
    merged.update(raw)
    merged["_source_path"] = str(path)
    return merged
