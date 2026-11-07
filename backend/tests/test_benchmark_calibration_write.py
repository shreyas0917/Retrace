"""`benchmark report` writes the calibrator only when explicitly asked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.cli.benchmark_cmd import render_markdown, run_report
from app.db import session as db_session
from app.services.diagnosis.calibration import reset_calibrator_cache


@pytest.fixture()
def calib_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "calibration.json"
    monkeypatch.setenv("CALIBRATION_PATH", str(path))
    reset_calibrator_cache()
    yield path
    reset_calibrator_cache()


def _report(write: bool) -> dict:
    db_session.init_db()
    assert db_session.SessionLocal is not None
    db = db_session.SessionLocal()
    try:
        return run_report(
            db,
            suite_id="planted_v1",
            suite_version="1.0.0",
            calibrate_on="planted_v1",
            calibrate_version="1.0.0",
            with_llm=False,
            classifier_limit=None,
            n_bins=10,
            write_calibration=write,
        )
    finally:
        db.close()


def test_report_does_not_write_calibration_by_default(calib_path: Path) -> None:
    report = _report(write=False)
    assert not calib_path.exists()
    assert report["calibration_fit"]["written"] is False
    assert report["calibration_fit"]["path"] is None
    md = render_markdown(report)
    assert "not written" in md and "--write-calibration" in md


def test_report_writes_calibration_only_with_flag(calib_path: Path) -> None:
    report = _report(write=True)
    assert calib_path.is_file()
    saved = json.loads(calib_path.read_text(encoding="utf-8"))
    assert saved["fitted_on"].startswith("planted_v1@1.0.0")
    assert report["calibration_fit"]["written"] is True
    assert "written to `backend/configs/calibration.json`" in render_markdown(report)
