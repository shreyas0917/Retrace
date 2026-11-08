#!/usr/bin/env python3
"""Blind labelling sheet for live_v1, and merging the author's labels.

    python -I scripts/live_labelling.py export          # stdlib only
    scripts/dev_test.sh python /scripts/live_labelling.py merge --dry-run
    scripts/dev_test.sh python /scripts/live_labelling.py merge

`export` reads backend/datasets/suites/live_v1/v1.0.0/runs.jsonl and writes, under
data/labelling/:

* live_v1_sheet.csv     one row per case: query, ranked retrieved chunks and
                        the answer, then empty columns for the labeller.
* live_v1_sheet.html    the same cases, easier to read. Labels go in the CSV.
* live_v1_corpus_chunks.csv   every chunk of the main demo corpus, for
                        choosing gold chunk ids.

The sheet is blind. It never contains the injected condition, the generator
fault, the corpus variant, any judge output, or Retrace's diagnosis. Cases are
shuffled into sheet ids (S01, S02, ...) by a fixed hash of the query id, so
neither the order nor the id gives the condition away. The merge step
recomputes the same mapping, so no key file is written next to the sheet.

`merge` reads the labelled sheet back, maps each sheet id to its run with the
same salted order, validates every row (all problems are reported at once),
and writes cases.jsonl and manifest.json: one GoldCase per run, carrying the
author's labels and the recorded run as its offline execution. It refuses to
overwrite an existing cases.jsonl unless --force is given. `merge` needs the
backend package (it validates against the suite schema), so run it in the
backend image or with backend/ importable.

Labelling rules: docs/labelling-guide.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if Path("/app/datasets/suites").is_dir() and Path("/data").is_dir():
    # Inside the backend image (scripts/dev_test.sh mounts these).
    SUITE_DIR = Path("/app/datasets/suites/live_v1/v1.0.0")
    OUT_DIR = Path("/data/labelling")
else:
    SUITE_DIR = ROOT / "backend" / "datasets" / "suites" / "live_v1" / "v1.0.0"
    OUT_DIR = ROOT / "data" / "labelling"
SHEET_SALT = "retrace-live_v1-sheet-v1"

LABEL_COLUMNS = (
    "failure_label",
    "acceptable_primary_codes",
    "gold_chunk_ids",
    "should_abstain",
    "expected_answer",
    "notes",
)
SHEET_COLUMNS = ("sheet_id", "query", "retrieved_chunks", "answer") + LABEL_COLUMNS
NO_ANSWER_STATUSES = {"GENERATION_TIMEOUT", "FAILED"}

# Codes a labeller may use (docs/labelling-guide.md). DIAGNOSIS_UNCERTAIN and
# EVAL_JUDGE_MALFORMED describe Retrace itself, not the run, so they are not labels.
LABEL_CODES = (
    "OK_GROUNDED",
    "OK_CORRECT_ABSTENTION",
    "RETRIEVAL_EMPTY",
    "RETRIEVAL_MISS",
    "RETRIEVAL_DISTRACTOR_DOMINANT",
    "RETRIEVAL_INSUFFICIENT_CONTEXT",
    "ABSTENTION_FALSE_NEGATIVE",
    "ABSTENTION_FALSE_POSITIVE",
    "GENERATION_CONTRADICTION",
    "GROUNDING_PARTIAL",
    "GROUNDING_UNSUPPORTED",
    "GENERATION_HALLUCINATION",
    "EVAL_MODEL_TIMEOUT",
    "EVAL_INTERNAL_ERROR",
)
YES = {"yes", "y", "true", "1"}
NO = {"no", "n", "false", "0"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sheet_order(records: list[dict]) -> list[tuple[str, dict]]:
    """Deterministic blind order: sort by a salted hash of the query id."""
    keyed = sorted(records, key=lambda r: hashlib.sha256(f"{SHEET_SALT}:{r['query_id']}".encode()).hexdigest())
    width = max(2, len(str(len(keyed))))
    return [(f"S{i:0{width}d}", r) for i, r in enumerate(keyed, start=1)]


def chunk_lines(record: dict) -> list[tuple[int, str, str]]:
    chunks = (record.get("execution") or {}).get("retrieved_chunks") or []
    out = []
    for position, chunk in enumerate(chunks, start=1):
        rank = chunk.get("rank") or position
        out.append((int(rank), str(chunk.get("chunk_id") or "?"), str(chunk.get("text") or "").strip()))
    return sorted(out)


def answer_text(record: dict) -> str:
    execution = record.get("execution") or {}
    answer = execution.get("answer")
    status = execution.get("status")
    if status in NO_ANSWER_STATUSES and not answer:
        return f"(no answer: pipeline status {status})"
    return str(answer or "(empty answer)")


def blind_row(sheet_id: str, record: dict) -> dict[str, str]:
    retrieved = (
        "\n\n".join(f"#{rank} [{cid}]\n{text}" for rank, cid, text in chunk_lines(record)) or "(no chunks retrieved)"
    )
    row = {"sheet_id": sheet_id, "query": record["query"], "retrieved_chunks": retrieved, "answer": answer_text(record)}
    row.update({c: "" for c in LABEL_COLUMNS})
    return row


def render_html(rows: list[tuple[str, dict]]) -> str:
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>live_v1 labelling</title><style>",
        ":root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#5d5b55;--line:#dedad1;--card:#fff;--accent:#3b5bdb}",
        "@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--muted:#a5a39b;--line:#34332f;--card:#1f1f1c;--accent:#91a7ff}}",
        "body{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,sans-serif;margin:0;padding:24px 16px}",
        "main{max-width:860px;margin:0 auto}h1{font-size:22px}section{background:var(--card);border:1px solid var(--line);",
        "border-radius:8px;padding:16px 18px;margin:18px 0}h2{font-size:16px;margin:0 0 8px}",
        ".k{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em;margin-top:12px}",
        ".chunk{border-left:3px solid var(--line);padding:2px 0 2px 10px;margin:8px 0;white-space:pre-wrap}",
        ".cid{font:12px ui-monospace,monospace;color:var(--accent)}.answer{white-space:pre-wrap}",
        "</style></head><body><main>",
        "<h1>live_v1 labelling sheet</h1>",
        "<p>Read the cases here; write labels in <code>live_v1_sheet.csv</code>. "
        "Rules and code meanings: <code>docs/labelling-guide.md</code>. "
        "Gold chunk ids: <code>live_v1_corpus_chunks.csv</code>.</p>",
    ]
    for sheet_id, record in rows:
        parts.append(f"<section id='{sheet_id}'><h2>{sheet_id}</h2>")
        parts.append(f"<div class='k'>Question</div><div>{html.escape(record['query'])}</div>")
        parts.append("<div class='k'>Retrieved chunks (rank order)</div>")
        lines = chunk_lines(record)
        if not lines:
            parts.append("<div class='chunk'>(no chunks retrieved)</div>")
        for rank, cid, text in lines:
            parts.append(
                f"<div class='chunk'><span class='cid'>#{rank} {html.escape(cid)}</span>\n{html.escape(text)}</div>"
            )
        parts.append(
            f"<div class='k'>Answer</div><div class='answer'>{html.escape(answer_text(record))}</div></section>"
        )
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


def export(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite_dir)
    out_dir = Path(args.out_dir)
    runs = suite_dir / "runs.jsonl"
    if not runs.is_file():
        print(f"export: {runs} not found; run scripts/build_live_suite.py first", file=sys.stderr)
        return 2
    rows = sheet_order(read_jsonl(runs))
    sheet = out_dir / "live_v1_sheet.csv"
    if sheet.exists() and not args.force:
        print(f"export: {sheet} exists (it may hold labels); pass --force to overwrite", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    with sheet.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for sheet_id, record in rows:
            writer.writerow(blind_row(sheet_id, record))
    (out_dir / "live_v1_sheet.html").write_text(render_html(rows), encoding="utf-8", newline="\n")

    inventory = suite_dir / "corpus_chunks.jsonl"
    if inventory.is_file():
        with (out_dir / "live_v1_corpus_chunks.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["chunk_id", "document_id", "text"])
            for chunk in read_jsonl(inventory):
                writer.writerow([chunk["chunk_id"], chunk["document_id"], chunk["text"]])
    print(f"wrote {sheet} ({len(rows)} cases), live_v1_sheet.html and live_v1_corpus_chunks.csv")
    return 0


# --------------------------------------------------------------------------
# merge
# --------------------------------------------------------------------------
class SheetError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__(f"{len(problems)} problem(s) in the labelling sheet")
        self.problems = problems


def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").replace(",", ";").split(";") if part.strip()]


def read_labels(sheet_path: Path, records: list[dict], inventory: list[dict]) -> dict[str, dict]:
    """Labels keyed by query id. Raises SheetError listing every problem."""
    by_sheet = dict(sheet_order(records))
    chunk_ids = {c["chunk_id"] for c in inventory}
    doc_chunks: dict[str, list[str]] = {}
    for chunk in inventory:
        doc_chunks.setdefault(chunk["document_id"], []).append(chunk["chunk_id"])

    with sheet_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing_cols = [c for c in SHEET_COLUMNS if c not in (reader.fieldnames or [])]
        if missing_cols:
            raise SheetError([f"sheet is missing columns: {', '.join(missing_cols)}"])
        rows = list(reader)

    problems: list[str] = []
    labels: dict[str, dict] = {}
    seen: set[str] = set()
    for line_no, row in enumerate(rows, start=2):
        sid = (row.get("sheet_id") or "").strip()
        where = sid or f"line {line_no}"
        if sid not in by_sheet:
            problems.append(f"{where}: unknown sheet id")
            continue
        if sid in seen:
            problems.append(f"{where}: appears twice")
            continue
        seen.add(sid)
        record = by_sheet[sid]
        if (row.get("query") or "").strip() != record["query"].strip():
            problems.append(f"{where}: the question differs from the recorded run (stale sheet, or the row was edited)")
            continue

        label = (row.get("failure_label") or "").strip().upper()
        if not label:
            problems.append(f"{where}: failure_label is empty")
        elif label not in LABEL_CODES:
            problems.append(f"{where}: failure_label {label!r} is not a labelling code")

        extras: list[str] = []
        for code in (c.upper() for c in _split(row.get("acceptable_primary_codes", ""))):
            if code not in LABEL_CODES:
                problems.append(f"{where}: acceptable code {code!r} is not a labelling code")
            elif code != label and code not in extras:
                extras.append(code)

        gold_raw = (row.get("gold_chunk_ids") or "").strip()
        gold: list[str] = []
        if not gold_raw:
            problems.append(f"{where}: gold_chunk_ids is empty (write 'none' if the policies do not answer it)")
        elif gold_raw.lower() != "none":
            for token in _split(gold_raw):
                if token in chunk_ids:
                    found = [token]
                elif token in doc_chunks:
                    found = doc_chunks[token]
                else:
                    problems.append(f"{where}: {token!r} is neither a chunk id nor a document id of the main corpus")
                    continue
                gold.extend(cid for cid in found if cid not in gold)
        if label == "RETRIEVAL_MISS" and gold_raw.lower() == "none":
            problems.append(f"{where}: RETRIEVAL_MISS needs the gold chunk ids that were missed, not 'none'")

        abstain_raw = (row.get("should_abstain") or "").strip().lower()
        if abstain_raw in YES:
            should_abstain = True
        elif abstain_raw in NO:
            should_abstain = False
        else:
            problems.append(f"{where}: should_abstain must be yes or no")
            should_abstain = False

        labels[record["query_id"]] = {
            "sheet_id": sid,
            "failure_label": label,
            "acceptable_primary_codes": [label, *extras],
            "relevant_chunk_ids": gold,
            "expected_abstention": should_abstain,
            "expected_answer": (row.get("expected_answer") or "").strip() or None,
            "notes": (row.get("notes") or "").strip() or None,
        }
    for sid in sorted(set(by_sheet) - seen):
        problems.append(f"{sid}: missing from the sheet")
    if problems:
        raise SheetError(problems)
    return labels


def _backend_imports():
    backend = Path("/app") if Path("/app/app").is_dir() else ROOT / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.services.eval.live_suite import record_to_offline_execution, runs_hash
    from app.services.eval.schemas import GoldCase
    from app.services.eval.suite_loader import compute_suite_hash

    return record_to_offline_execution, runs_hash, GoldCase, compute_suite_hash


def build_cases(records: list[dict], labels: dict[str, dict], *, annotator: str, annotation_date: str) -> list[dict]:
    record_to_offline_execution, _, gold_case, _ = _backend_imports()
    cases = []
    for record in sorted(records, key=lambda r: r["query_id"]):
        label = labels[record["query_id"]]
        corpus = record.get("corpus") or {}
        case = {
            "case_id": record["query_id"],
            "suite_id": record.get("suite_id", "live_v1"),
            "suite_version": record.get("suite_version", "1.0.0"),
            "corpus_id": "demo",
            "corpus_version_pin": f"{corpus.get('corpus_id')}@{corpus.get('corpus_hash')}",
            "query": record["query"],
            "expected_answer": label["expected_answer"],
            "expected_abstention": label["expected_abstention"],
            "relevant_chunk_ids": label["relevant_chunk_ids"],
            "failure_label": label["failure_label"],
            "acceptable_primary_codes": label["acceptable_primary_codes"],
            "planted_failure": None,
            "notes": label["notes"],
            "annotator": annotator,
            "annotation_date": annotation_date,
            "taxonomy_version": "1.0",
            # The injected condition is metadata for the per-condition breakdown, not the label.
            "tags": [
                f"condition:{record['condition']}",
                f"corpus_variant:{record['corpus_variant']}",
                f"eval_fault:{record.get('eval_fault') or 'none'}",
            ],
            "expected_rule_id": None,
            "expected_evidence_chunk_ids": None,
            "offline_execution": record_to_offline_execution(record).model_dump(mode="json"),
        }
        gold_case.model_validate(case)
        cases.append(case)
    return cases


def merge(args: argparse.Namespace) -> int:
    suite_dir = Path(args.suite_dir)
    sheet_path = Path(args.sheet)
    runs_path = suite_dir / "runs.jsonl"
    for path in (runs_path, suite_dir / "corpus_chunks.jsonl", sheet_path):
        if not path.is_file():
            print(f"merge: {path} not found", file=sys.stderr)
            return 2
    cases_path = suite_dir / "cases.jsonl"
    if cases_path.exists() and not args.force and not args.dry_run:
        print(f"merge: {cases_path} already exists; pass --force to replace it", file=sys.stderr)
        return 2

    runs_lines = runs_path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in runs_lines if line.strip()]
    inventory = read_jsonl(suite_dir / "corpus_chunks.jsonl")
    try:
        labels = read_labels(sheet_path, records, inventory)
    except SheetError as exc:
        print(f"merge: {exc}; nothing was written", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    cases = build_cases(records, labels, annotator=args.annotator, annotation_date=args.date)
    _, runs_hash, _, compute_suite_hash = _backend_imports()
    lines = [json.dumps(case, ensure_ascii=False) for case in cases]
    suite_hash = compute_suite_hash(lines)
    label_counts: dict[str, int] = {}
    for case in cases:
        label_counts[case["failure_label"]] = label_counts.get(case["failure_label"], 0) + 1
    ambiguous = sum(1 for c in cases if len(c["acceptable_primary_codes"]) > 1)
    manifest = {
        "suite_id": "live_v1",
        "suite_version": "1.0.0",
        "suite_hash": suite_hash,
        "case_count": len(cases),
        "taxonomy_version": "1.0",
        "annotator": args.annotator,
        "annotation_date": args.date,
        "provenance": (
            "Real pipeline runs recorded in runs.jsonl, labelled blind by the author from "
            "data/labelling/live_v1_sheet.csv. Injected conditions are tags, not labels."
        ),
        "runs_hash": runs_hash(runs_lines),
        "labels_sheet_sha256": "sha256:" + hashlib.sha256(sheet_path.read_bytes()).hexdigest(),
        "label_counts": dict(sorted(label_counts.items())),
        "cases_with_alternative_codes": ambiguous,
    }
    print(f"merge: {len(cases)} cases, {ambiguous} with alternative codes; labels {manifest['label_counts']}")
    if args.dry_run:
        print("merge: dry run, nothing written")
        return 0
    cases_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    (suite_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    runs_manifest_path = suite_dir / "runs_manifest.json"
    if runs_manifest_path.is_file():
        runs_manifest = json.loads(runs_manifest_path.read_text(encoding="utf-8"))
        runs_manifest["status"] = "recorded and labelled"
        runs_manifest_path.write_text(json.dumps(runs_manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {cases_path} ({suite_hash}) and manifest.json")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="Write the blind labelling sheet")
    p.add_argument("--suite-dir", default=str(SUITE_DIR))
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--force", action="store_true", help="Overwrite an existing sheet")
    p.set_defaults(func=export)
    m = sub.add_parser("merge", help="Merge the labelled sheet into cases.jsonl")
    m.add_argument("--suite-dir", default=str(SUITE_DIR))
    m.add_argument("--sheet", default=str(OUT_DIR / "live_v1_sheet.csv"))
    m.add_argument("--annotator", default="author")
    m.add_argument("--date", default=date.today().isoformat(), help="Annotation date (YYYY-MM-DD)")
    m.add_argument("--dry-run", action="store_true", help="Validate and summarise; write nothing")
    m.add_argument("--force", action="store_true", help="Replace an existing cases.jsonl")
    m.set_defaults(func=merge)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
