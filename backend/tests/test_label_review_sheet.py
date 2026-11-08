"""The judge-label review tool: export a sheet, apply the author's corrections."""

from __future__ import annotations

import csv
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from app.services.eval.suite_loader import compute_suite_hash

DATASETS = Path(__file__).resolve().parents[1] / "datasets" / "judges"


def _load_tool():
    # Repo layout locally; /scripts inside the dev_test.sh container.
    for candidate in (
        Path(__file__).resolve().parents[2] / "scripts" / "judge_labels_review.py",
        Path("/scripts/judge_labels_review.py"),
    ):
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("judge_labels_review", candidate)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    pytest.skip("scripts/judge_labels_review.py not available in this environment")


tool = _load_tool()


@pytest.fixture()
def workspace(tmp_path: Path):
    dataset = tmp_path / "labels.jsonl"
    manifest = tmp_path / "manifest.json"
    shutil.copy(DATASETS / "judge_labels_v1.jsonl", dataset)
    shutil.copy(DATASETS / "manifest.json", manifest)
    sheet = tmp_path / "review.csv"
    tool.export_sheet(dataset, sheet)
    return dataset, manifest, sheet


def _read(sheet: Path) -> list[dict[str, str]]:
    with sheet.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write(sheet: Path, rows: list[dict[str, str]]) -> None:
    with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=tool.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _set_correction(sheet: Path, row_id: str, value: str) -> None:
    rows = _read(sheet)
    for r in rows:
        if r["row_id"] == row_id:
            r["correction"] = value
    _write(sheet, rows)


def test_export_has_one_row_per_label(workspace):
    _dataset, _manifest, sheet = workspace
    rows = _read(sheet)
    assert len(rows) == 173
    assert len({r["row_id"] for r in rows}) == 173
    assert len({r["example_id"] for r in rows}) == 66
    assert all(r["correction"] == "" and r["current_label"] for r in rows)
    # Tags and rationale notes stay off the sheet so they cannot steer the review.
    assert not any("numerically_wrong" in r["input"] for r in rows)


def test_apply_without_corrections_marks_reviewed_and_rehashes(workspace):
    dataset, manifest, sheet = workspace
    before = tool.label_counts(tool.load_rows(dataset))
    summary = tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-09")
    assert summary["changed_labels"] == 0
    assert summary["reviewed_units"] == 173
    rows = tool.load_rows(dataset)
    assert all(r["annotator"] == "ai_draft_author_reviewed" for r in rows)
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    raw = dataset.read_text(encoding="utf-8").splitlines()
    # The script's hash must agree with the backend loader's hash.
    assert meta["dataset_hash"] == compute_suite_hash(raw)
    assert meta["review"]["changed_labels"] == 0
    assert meta["annotator"] == "ai_draft_author_reviewed"
    assert meta["label_counts"] == before


def test_ai_review_is_recorded_as_provisional_and_worded_so(workspace):
    from app.cli.judges_cmd import PROVISIONAL_BANNER, label_provenance

    dataset, manifest, sheet = workspace
    assert manifest == dataset.with_name("manifest.json")  # label_provenance reads it from there
    tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-09", annotator="ai_draft_blind")
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    assert meta["annotator"] == "ai_draft_blind" and meta["provisional"] is True
    assert meta["review"]["reviewed_by"] == "ai_agent_blind"
    assert "not yet reviewed by the author" in meta["source"]
    assert all(r["annotator"] == "ai_draft_blind" for r in tool.load_rows(dataset))
    text, provisional = label_provenance(dataset)
    assert provisional and "Not yet reviewed by the author" in text and "0 of 173" in text
    assert "PROVISIONAL" in PROVISIONAL_BANNER

    tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-10")
    text, provisional = label_provenance(dataset)
    assert not provisional
    assert text == "Labels: AI-drafted, reviewed and corrected by the author (0 of 173 labels changed)."
    with pytest.raises(tool.ReviewError):
        tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-10", annotator="someone")


def test_apply_counts_real_changes_and_warns_on_stale_band(workspace):
    dataset, manifest, sheet = workspace
    _set_correction(sheet, "fai_001#claim-1", "false")
    # Re-entering the current value is a confirmation, not a change.
    _set_correction(sheet, "con_001#contradicts", "true")
    summary = tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-09", dry_run=True)
    assert summary["changed_labels"] == 1
    assert any(w.startswith("fai_001:") for w in summary["band_warnings"])

    _set_correction(sheet, "fai_001#faithfulness_band", "0.5-0.5")
    summary = tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-09")
    assert summary["changed_labels"] == 2
    assert not any(w.startswith("fai_001:") for w in summary["band_warnings"])
    row = next(r for r in tool.load_rows(dataset) if r["example_id"] == "fai_001")
    assert row["claims"][0]["supported"] is False
    assert row["faithfulness_band"] == [0.5, 0.5]


def test_dry_run_writes_nothing(workspace):
    dataset, manifest, sheet = workspace
    before = (dataset.read_bytes(), manifest.read_bytes())
    _set_correction(sheet, "rel_001#chunk-1", "false")
    tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-09", dry_run=True)
    assert (dataset.read_bytes(), manifest.read_bytes()) == before


def test_stale_sheet_and_bad_values_are_rejected(workspace):
    dataset, manifest, sheet = workspace
    _set_correction(sheet, "rel_001#chunk-1", "maybe")
    with pytest.raises(tool.ReviewError, match="not true/false"):
        tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-09")

    _set_correction(sheet, "rel_001#chunk-1", "")
    _set_correction(sheet, "fai_001#faithfulness_band", "0.9-0.2")
    with pytest.raises(tool.ReviewError, match="lo-hi"):
        tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-09")

    rows = [r for r in _read(sheet) if r["row_id"] != "con_001#contradicts"]
    _write(sheet, rows)
    with pytest.raises(tool.ReviewError, match="does not match"):
        tool.apply_sheet(dataset, manifest, sheet, review_date="2026-11-09")


def test_export_refuses_to_overwrite_a_filled_sheet(workspace):
    dataset, _manifest, sheet = workspace
    _set_correction(sheet, "rel_001#chunk-1", "false")
    with pytest.raises(tool.ReviewError, match="refusing to overwrite"):
        tool.export_sheet(dataset, sheet)
    assert tool.export_sheet(dataset, sheet, force=True) == 173
