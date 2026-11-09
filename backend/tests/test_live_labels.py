"""live_v1 label merge and report, exercised on copies in a temp folder.

The real suite directory is only ever read: runs are copied into tmp_path,
labelled there with made-up labels, merged and reported. Nothing here writes
under backend/datasets/suites/live_v1.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.db import session as db_session
from app.services.diagnosis.taxonomy import FAILURE_CODES
from app.services.eval import suite_loader
from app.services.eval.live_report import attribute_miss, bootstrap_ci, render_live_markdown, run_live_report
from app.services.judges.faithfulness_nli import NLIScorer, set_nli_scorer

REAL_SUITE = Path(__file__).resolve().parents[1] / "datasets" / "suites" / "live_v1" / "v1.0.0"
N_CASES = 8


def _load_script(name: str):
    for candidate in (Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py", Path(f"/scripts/{name}.py")):
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(name, candidate)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(module)
            return module
    pytest.skip(f"scripts/{name}.py not available in this environment")


tool = _load_script("live_labelling")


def _exploding_scorer() -> NLIScorer:
    def boom(pairs):
        raise AssertionError("the NLI model must not run: live_v1 replays recorded outputs")

    return NLIScorer(
        predict_probs=boom,
        id2label={0: "contradiction", 1: "entailment", 2: "neutral"},
        token_spans=lambda t: [(0, len(t))],
        max_length=512,
    )


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch):
    if not (REAL_SUITE / "runs.jsonl").is_file():
        pytest.skip("live_v1 runs are not recorded in this checkout")
    real_cases = REAL_SUITE / "cases.jsonl"
    real_cases_existed = real_cases.exists()
    root = tmp_path / "suites"
    suite = root / "live_v1" / "v1.0.0"
    suite.mkdir(parents=True)
    records = [
        json.loads(line)
        for line in (REAL_SUITE / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # One record per condition first, so every condition is represented, then fill up.
    picked, seen = [], set()
    for r in records:
        if r["condition"] not in seen:
            picked.append(r)
            seen.add(r["condition"])
    picked += [r for r in records if r not in picked][: N_CASES - len(picked)]
    (suite / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in picked) + "\n", encoding="utf-8")
    for name in ("queries.jsonl", "corpus_chunks.jsonl", "runs_manifest.json"):
        shutil.copy(REAL_SUITE / name, suite / name)
    out = tmp_path / "labelling"
    assert tool.export(SimpleNamespace(suite_dir=str(suite), out_dir=str(out), force=False)) == 0
    monkeypatch.setattr(suite_loader, "default_suites_root", lambda: root)
    set_nli_scorer(_exploding_scorer())
    yield SimpleNamespace(root=root, suite=suite, sheet=out / "live_v1_sheet.csv", records=picked)
    set_nli_scorer(None)
    # The real suite must not have gained a cases.jsonl from these tests.
    assert real_cases.exists() == real_cases_existed


def _fill(sheet: Path, records: list[dict], edit=None) -> None:
    """Made-up labels for the test: the live prediction for most rows, a different code for some."""
    by_sheet = dict(tool.sheet_order(records))
    with sheet.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for i, row in enumerate(rows):
        rec = by_sheet[row["sheet_id"]]
        live = rec["live_diagnosis"]["failure_code"]
        label = live if live in tool.LABEL_CODES and i % 3 else "OK_GROUNDED"
        row.update(
            failure_label=label,
            acceptable_primary_codes="GROUNDING_PARTIAL" if i == 1 else "",
            gold_chunk_ids="none",
            should_abstain="yes" if rec["execution"]["abstained"] else "no",
            expected_answer="",
            notes="test label" if i == 2 else "",
        )
    if rows:
        # A main-corpus chunk id; distractor chunks are not valid gold ids.
        inventory = {
            json.loads(line)["chunk_id"]
            for line in (REAL_SUITE / "corpus_chunks.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        retrieved = re.findall(r"#\d+ \[([^\]]+)\]", rows[0]["retrieved_chunks"])
        rows[0]["gold_chunk_ids"] = next((c for c in retrieved if c in inventory), sorted(inventory)[0])
        rows[-1]["gold_chunk_ids"] = "employee_handbook"  # a document id, expanded to its chunks
    if edit:
        edit(rows)
    with sheet.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=tool.SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _merge_args(ws, **kw):
    return SimpleNamespace(
        suite_dir=str(ws.suite),
        sheet=str(kw.get("sheet", ws.sheet)),
        annotator=kw.get("annotator", "author"),
        draft=kw.get("draft"),
        date="2026-11-08",
        dry_run=kw.get("dry_run", False),
        force=kw.get("force", False),
    )


# --- merge -------------------------------------------------------------------


def test_label_codes_match_the_taxonomy_and_the_guide() -> None:
    assert set(tool.LABEL_CODES) <= set(FAILURE_CODES)
    assert not {"DIAGNOSIS_UNCERTAIN", "EVAL_JUDGE_MALFORMED"} & set(tool.LABEL_CODES)
    assert not any(FAILURE_CODES[c].reserved for c in tool.LABEL_CODES)
    for guide in (
        Path(__file__).resolve().parents[2] / "docs" / "labelling-guide.md",
        Path("/docs/labelling-guide.md"),
    ):
        if guide.is_file():
            table = (
                guide.read_text(encoding="utf-8").split("## Failure codes in plain English", 1)[1].split("## ", 1)[0]
            )
            assert set(re.findall(r"^\| `([A-Z_]+)` \|", table, flags=re.M)) == set(tool.LABEL_CODES)
            break


def test_merge_writes_a_valid_suite_from_the_sheet(workspace) -> None:
    _fill(workspace.sheet, workspace.records)
    assert tool.merge(_merge_args(workspace, dry_run=True)) == 0
    assert not (workspace.suite / "cases.jsonl").exists()

    assert tool.merge(_merge_args(workspace)) == 0
    cases, suite_hash, _ = suite_loader.load_suite("live_v1", "1.0.0", root=workspace.root)
    manifest = json.loads((workspace.suite / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["suite_hash"] == suite_hash and manifest["case_count"] == len(workspace.records)
    assert manifest["annotator"] == "author" and manifest["cases_with_alternative_codes"] == 1
    assert (
        json.loads((workspace.suite / "runs_manifest.json").read_text(encoding="utf-8"))["status"]
        == "recorded and labelled"
    )
    by_id = {c.case_id: c for c in cases}
    assert set(by_id) == {r["query_id"] for r in workspace.records}
    for record in workspace.records:
        case = by_id[record["query_id"]]
        assert f"condition:{record['condition']}" in case.tags
        assert case.offline_execution.answer == record["execution"]["answer"]
        assert case.offline_execution.judge_scripts.get("faithfulness_nli") == record["judges"]["faithfulness_nli"]
        assert case.failure_label in case.acceptable_primary_codes
    expanded = [c for c in cases if len(c.relevant_chunk_ids) > 1]
    assert expanded and all(cid.startswith("employee_handbook:") for cid in expanded[0].relevant_chunk_ids)
    # An existing suite is not replaced without --force.
    assert tool.merge(_merge_args(workspace)) == 2
    assert tool.merge(_merge_args(workspace, force=True)) == 0


def test_merge_reports_every_problem_and_writes_nothing(workspace, capsys) -> None:
    def break_rows(rows):
        rows[0]["failure_label"] = ""
        rows[1]["failure_label"] = "PROBABLY_FINE"
        rows[2]["gold_chunk_ids"] = "no_such_doc:c999"
        rows[3]["should_abstain"] = "maybe"
        rows[4]["query"] = rows[4]["query"] + " (edited)"
        rows[5]["failure_label"], rows[5]["gold_chunk_ids"] = "RETRIEVAL_MISS", "none"
        rows[6]["gold_chunk_ids"] = ""
        del rows[7]

    _fill(workspace.sheet, workspace.records, edit=break_rows)
    assert tool.merge(_merge_args(workspace)) == 1
    err = capsys.readouterr().err
    for fragment in (
        "failure_label is empty",
        "'PROBABLY_FINE' is not a labelling code",
        "neither a chunk id",
        "should_abstain must be yes or no",
        "question differs",
        "RETRIEVAL_MISS needs",
        "gold_chunk_ids is empty",
        "missing from the sheet",
    ):
        assert fragment in err, fragment
    assert not (workspace.suite / "cases.jsonl").exists()


# --- report ------------------------------------------------------------------


def test_live_report_runs_offline_and_renders(workspace) -> None:
    _fill(workspace.sheet, workspace.records)
    assert tool.merge(_merge_args(workspace)) == 0
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        report = run_live_report(db)
    finally:
        db.close()
    s = report["summary"]
    assert s["total_cases"] == len(workspace.records)
    assert len(report["misses"]) == s["incorrect"]
    for key in ("lenient_accuracy", "strict_accuracy", "macro_f1"):
        ci = report["confidence_intervals"][key]
        assert ci["low"] <= ci["point"] <= ci["high"]
    assert set(report["conditions"]) == {r["condition"] for r in workspace.records}
    assert sum(c["n"] for c in report["conditions"].values()) == len(workspace.records)
    assert report["runs"]["generation_models"] == ["llama3.2:latest"]
    text = render_live_markdown(report)
    for heading in (
        "## Results",
        "## Per class (strict)",
        "## By injected condition",
        "## Confusion matrix",
        "## Error analysis",
        "## Limits",
    ):
        assert heading in text
    assert "95% CI" in text
    assert report["timeouts"] == 0 and report["model_timeout_seconds"] == [600.0]
    assert (
        "One labeller (author)" in text
        and "0 run(s) timed out" in text
        and "`ABS-FN`" not in text.split("## Confusion matrix")[0]
    )


def _render(workspace) -> str:
    db_session.init_db()
    db = db_session.SessionLocal()
    try:
        return render_live_markdown(run_live_report(db))
    finally:
        db.close()


AI_WORDING = (
    "labelled blind by an independent AI annotator (fresh subagent, no access to Retrace predictions); "
    "not yet reviewed by a human"
)


def test_ai_labels_say_who_labelled_them_everywhere(workspace) -> None:
    _fill(workspace.sheet, workspace.records)
    assert tool.merge(_merge_args(workspace, annotator="ai_draft_blind")) == 0
    manifest = json.loads((workspace.suite / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["annotator"] == "ai_draft_blind" and manifest["human_reviewed"] is False
    assert AI_WORDING in manifest["provenance"]
    text = _render(workspace)
    assert AI_WORDING in text and "PROVISIONAL" not in text
    assert "## What this does and doesn't show" in text and "Suggested cause" in text
    assert "One labeller (author)" not in text


def test_reviewed_merge_counts_the_cases_the_author_changed(workspace, tmp_path) -> None:
    draft = tmp_path / "draft.csv"
    draft.write_bytes(workspace.sheet.read_bytes())
    _fill(draft, workspace.records)

    def change_two(rows):
        rows[0]["failure_label"] = "RETRIEVAL_EMPTY" if rows[0]["failure_label"] != "RETRIEVAL_EMPTY" else "OK_GROUNDED"
        rows[1]["should_abstain"] = "no" if rows[1]["should_abstain"] == "yes" else "yes"
        rows[2]["notes"] = "a note is not a label change"

    _fill(workspace.sheet, workspace.records, edit=change_two)
    args = _merge_args(workspace, annotator="ai_draft_author_reviewed")
    assert tool.merge(args) == 2  # --draft is required
    reviewed = _merge_args(workspace, annotator="ai_draft_author_reviewed", draft=draft)
    assert tool.merge(reviewed) == 1  # no review_decision column

    def add_decisions(undecided: int) -> None:
        with workspace.sheet.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        for i, row in enumerate(rows):
            row["review_decision"] = "undecided" if i < undecided else ("change" if i < 2 else "agree")
        with workspace.sheet.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=[*tool.SHEET_COLUMNS, "review_decision"])
            writer.writeheader()
            writer.writerows(rows)

    add_decisions(undecided=1)
    assert tool.merge(reviewed) == 1  # an undecided row is refused
    add_decisions(undecided=0)
    assert tool.merge(reviewed) == 0
    manifest = json.loads((workspace.suite / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review"]["changed_cases"] == 2 and manifest["human_reviewed"] is True
    text = _render(workspace)
    assert f"AI-drafted, reviewed and corrected by the author (2 of {len(workspace.records)} changed)" in text
    assert "not yet reviewed by a human" not in text


def test_bootstrap_is_seeded_and_brackets_the_point() -> None:
    rows = [{"correct_failure_code": i % 4 != 0} for i in range(40)]
    metric = lambda rs: sum(r["correct_failure_code"] for r in rs) / len(rs)  # noqa: E731
    a, b = bootstrap_ci(rows, metric), bootstrap_ci(rows, metric)
    assert a == b and a["point"] == 0.75 and a["low"] < 0.75 < a["high"]
    assert bootstrap_ci([], metric)["point"] is None


@pytest.mark.parametrize(
    ("expected", "predicted", "signals", "label", "cause"),
    [
        (
            "OK_GROUNDED",
            "GROUNDING_PARTIAL",
            {"context_sufficient": True, "unsupported_claim_count": 1},
            {},
            "judge error: faithfulness",
        ),
        (
            "GENERATION_CONTRADICTION",
            "OK_GROUNDED",
            {"context_sufficient": True, "answer_contradicts_context": False},
            {},
            "judge error: contradiction",
        ),
        (
            "OK_CORRECT_ABSTENTION",
            "ABSTENTION_FALSE_POSITIVE",
            {"context_sufficient": True},
            {"expected_abstention": True},
            "judge error: relevance",
        ),
        ("OK_GROUNDED", "DIAGNOSIS_UNCERTAIN", {}, {}, "deferred"),
        ("OK_CORRECT_ABSTENTION", "RETRIEVAL_MISS", {"gold_hit": False}, {"expected_abstention": True}, "rule gap"),
    ],
)
def test_miss_attribution_first_pass(expected, predicted, signals, label, cause) -> None:
    result = {
        "case_id": "L01",
        "expected_failure_code": expected,
        "predicted_failure_code": predicted,
        "predicted_rule_id": "R00",
        "tags": ["condition:clean"],
        "explanation": "x",
    }
    out = attribute_miss(result, {"acceptable_primary_codes": [expected], **label}, signals)
    assert out["cause"] == cause and out["condition"] == "clean"
