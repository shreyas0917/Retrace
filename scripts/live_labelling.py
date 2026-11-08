#!/usr/bin/env python3
"""Blind labelling sheet for live_v1 (stdlib only).

    python -I scripts/live_labelling.py export

reads backend/datasets/suites/live_v1/v1.0.0/runs.jsonl and writes, under
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

Labelling rules: docs/labelling-guide.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
    retrieved = "\n\n".join(f"#{rank} [{cid}]\n{text}" for rank, cid, text in chunk_lines(record)) or "(no chunks retrieved)"
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
            parts.append(f"<div class='chunk'><span class='cid'>#{rank} {html.escape(cid)}</span>\n{html.escape(text)}</div>")
        parts.append(f"<div class='k'>Answer</div><div class='answer'>{html.escape(answer_text(record))}</div></section>")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("export", help="Write the blind labelling sheet")
    p.add_argument("--suite-dir", default=str(SUITE_DIR))
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--force", action="store_true", help="Overwrite an existing sheet")
    p.set_defaults(func=export)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
