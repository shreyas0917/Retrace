"""Confidence calibration for diagnosis scores.

The rule engine emits a heuristic `diagnosis_score` in [0, 1]. This module
measures how well that score predicts correctness (reliability bins, expected
calibration error, Brier score) and fits a histogram-binning calibrator that
maps raw scores to empirical accuracy observed on a calibration suite.

The calibrator is stored as JSON (default `backend/configs/calibration.json`)
and applied at diagnosis time to produce `calibrated_confidence`. It is fitted
on a suite that is disjoint from the held-out evaluation suite.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

CALIBRATION_VERSION = "calibration.v1"


@dataclass
class CalibrationBin:
    lo: float
    hi: float
    count: int
    mean_score: float | None
    accuracy: float | None


@dataclass
class CalibrationTable:
    version: str
    n_bins: int
    bins: list[CalibrationBin]
    fitted_on: str
    sample_size: int
    created_at: str
    ece_before: float | None = None
    brier_before: float | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalibrationTable":
        bins = [CalibrationBin(**b) for b in data.get("bins", [])]
        return cls(
            version=str(data.get("version") or CALIBRATION_VERSION),
            n_bins=int(data.get("n_bins") or len(bins)),
            bins=bins,
            fitted_on=str(data.get("fitted_on") or "unknown"),
            sample_size=int(data.get("sample_size") or 0),
            created_at=str(data.get("created_at") or ""),
            ece_before=data.get("ece_before"),
            brier_before=data.get("brier_before"),
            notes=dict(data.get("notes") or {}),
        )


def _clip(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else float(x)


def _bin_index(score: float, n_bins: int) -> int:
    score = _clip(score)
    idx = int(score * n_bins)
    return min(idx, n_bins - 1)


def reliability_bins(
    scores: Sequence[float], correct: Sequence[bool], n_bins: int = 10
) -> list[CalibrationBin]:
    """Equal-width bins over [0, 1] with mean score and empirical accuracy."""
    if n_bins <= 0:
        raise ValueError("n_bins must be > 0")
    if len(scores) != len(correct):
        raise ValueError("scores and correct must have equal length")
    sums = [0.0] * n_bins
    hits = [0] * n_bins
    counts = [0] * n_bins
    for s, c in zip(scores, correct):
        i = _bin_index(float(s), n_bins)
        sums[i] += _clip(float(s))
        hits[i] += 1 if c else 0
        counts[i] += 1
    bins: list[CalibrationBin] = []
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        n = counts[i]
        bins.append(
            CalibrationBin(
                lo=round(lo, 6),
                hi=round(hi, 6),
                count=n,
                mean_score=None if n == 0 else round(sums[i] / n, 6),
                accuracy=None if n == 0 else round(hits[i] / n, 6),
            )
        )
    return bins


def expected_calibration_error(bins: Sequence[CalibrationBin]) -> float | None:
    """ECE = sum_b (n_b / N) * |acc_b - conf_b|."""
    total = sum(b.count for b in bins)
    if total == 0:
        return None
    ece = 0.0
    for b in bins:
        if b.count == 0 or b.accuracy is None or b.mean_score is None:
            continue
        ece += (b.count / total) * abs(b.accuracy - b.mean_score)
    return round(ece, 6)


def brier_score(scores: Sequence[float], correct: Sequence[bool]) -> float | None:
    """Mean squared error between score and the 0/1 correctness outcome."""
    if not scores:
        return None
    if len(scores) != len(correct):
        raise ValueError("scores and correct must have equal length")
    total = 0.0
    for s, c in zip(scores, correct):
        total += (_clip(float(s)) - (1.0 if c else 0.0)) ** 2
    return round(total / len(scores), 6)


def fit_histogram_calibrator(
    scores: Sequence[float],
    correct: Sequence[bool],
    *,
    n_bins: int = 10,
    fitted_on: str = "unknown",
    notes: dict[str, Any] | None = None,
) -> CalibrationTable:
    bins = reliability_bins(scores, correct, n_bins=n_bins)
    return CalibrationTable(
        version=CALIBRATION_VERSION,
        n_bins=n_bins,
        bins=bins,
        fitted_on=fitted_on,
        sample_size=len(scores),
        created_at=datetime.now(timezone.utc).isoformat(),
        ece_before=expected_calibration_error(bins),
        brier_before=brier_score(scores, correct),
        notes=dict(notes or {}),
    )


def apply_calibration(table: CalibrationTable | None, score: float) -> float:
    """Map a raw score to the empirical accuracy of its bin.

    Falls back to the raw score when no table is loaded or the bin is empty
    (never invents a probability from zero observations).
    """
    if table is None or not table.bins:
        return _clip(score)
    idx = _bin_index(float(score), table.n_bins)
    b = table.bins[idx]
    if b.count == 0 or b.accuracy is None:
        return _clip(score)
    return _clip(b.accuracy)


def confidence_label(prob: float) -> str:
    if prob >= 0.85:
        return "high"
    if prob >= 0.6:
        return "medium"
    return "low"


# --- persistence --------------------------------------------------------


def default_calibration_path() -> Path:
    env = os.environ.get("CALIBRATION_PATH")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    return here.parents[3] / "configs" / "calibration.json"


def save_calibration(table: CalibrationTable, path: str | Path | None = None) -> Path:
    path = Path(path) if path else default_calibration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table.to_dict(), indent=2) + "\n", encoding="utf-8")
    reset_calibrator_cache()
    return path


def load_calibration(path: str | Path | None = None) -> CalibrationTable | None:
    path = Path(path) if path else default_calibration_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return CalibrationTable.from_dict(data)


_cache_lock = threading.Lock()
_cached: tuple[float, CalibrationTable | None] | None = None


def get_calibrator() -> CalibrationTable | None:
    """Cached loader keyed on file mtime so edits are picked up without restart."""
    global _cached
    path = default_calibration_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = -1.0
    with _cache_lock:
        if _cached is not None and _cached[0] == mtime:
            return _cached[1]
        table = load_calibration(path) if mtime >= 0 else None
        _cached = (mtime, table)
        return table


def reset_calibrator_cache() -> None:
    global _cached
    with _cache_lock:
        _cached = None
