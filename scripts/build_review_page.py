#!/usr/bin/env python3
"""Build data/labelling/REVIEW_ME.html: a one-case-per-screen review of the
AI-drafted live_v1 labels.

    python -I scripts/build_review_page.py

Inputs (all blind; nothing here knows how a run was produced or what Retrace
predicted):

* data/labelling/live_v1_sheet.ai_draft.csv   the AI draft (sheet columns + reason, confidence)
* data/labelling/live_v1_corpus_chunks.csv    the 13 official policies, for gold chunk ids
* docs/labelling-guide.md                     code meanings, shown as help

The page never reads runs.jsonl, queries.jsonl, corpus_variants.json or any
diagnosis output, so it cannot show a prediction or an injected condition.
It exports the reviewed sheet as live_v1_sheet.reviewed.csv (the sheet
columns plus review_decision), which `live_labelling.py merge --annotator
ai_draft_author_reviewed --draft data/labelling/live_v1_sheet.ai_draft.csv`
reads.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "data" / "labelling"
DRAFT = LAB / "live_v1_sheet.ai_draft.csv"
CHUNKS = LAB / "live_v1_corpus_chunks.csv"
GUIDE = ROOT / "docs" / "labelling-guide.md"
OUT = LAB / "REVIEW_ME.html"

SHEET_COLUMNS = [
    "sheet_id",
    "query",
    "retrieved_chunks",
    "answer",
    "failure_label",
    "acceptable_primary_codes",
    "gold_chunk_ids",
    "should_abstain",
    "expected_answer",
    "notes",
]
# Never let these into the page, whatever the draft file contains.
FORBIDDEN = {"condition", "corpus_variant", "eval_fault", "predicted", "rule_id", "diagnosis", "tags"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def guide_codes() -> list[dict[str, str]]:
    text = GUIDE.read_text(encoding="utf-8")
    table = text.split("## Failure codes in plain English", 1)[1].split("\n## ", 1)[0]
    return [
        {"code": m.group(1), "meaning": m.group(2).strip()}
        for m in re.finditer(r"^\| `([A-Z_]+)` \| (.+?) \|\s*$", table, flags=re.M)
    ]


def parse_chunks(block: str) -> list[dict[str, str]]:
    out = []
    block = block.replace("\r\n", "\n")
    for part in re.split(r"\n\n(?=#\d+ \[)", block.strip()):
        m = re.match(r"#(\d+) \[([^\]]+)\]\n?(.*)", part, flags=re.S)
        if m:
            out.append({"rank": m.group(1), "id": m.group(2), "text": m.group(3).strip()})
        elif part.strip():
            out.append({"rank": "", "id": "", "text": part.strip()})
    return out


def main() -> int:
    draft = read_csv(DRAFT)
    leaked = FORBIDDEN & set(draft[0].keys() if draft else [])
    if leaked:
        raise SystemExit(f"refusing to build: the draft has non-blind columns {sorted(leaked)}")
    chunks = read_csv(CHUNKS)
    cases = []
    for row in draft:
        case = {c: row.get(c, "") for c in SHEET_COLUMNS}
        case["reason"] = row.get("reason", "")
        case["confidence"] = (row.get("confidence") or "").strip().lower() or "high"
        case["chunks"] = parse_chunks(row["retrieved_chunks"])
        cases.append(case)
    # Low-confidence cases first, then sheet order.
    cases.sort(key=lambda c: (c["confidence"] != "low", c["sheet_id"]))
    data = {
        "cases": cases,
        "codes": guide_codes(),
        "corpus": [{"id": c["chunk_id"], "doc": c["document_id"], "text": c["text"]} for c in chunks],
        "columns": SHEET_COLUMNS,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    template = (Path(__file__).with_name("review_page_template.html")).read_text(encoding="utf-8")
    OUT.write_text(template.replace("/*__DATA__*/null", payload), encoding="utf-8", newline="\n")
    low = sum(c["confidence"] == "low" for c in cases)
    print(f"wrote {OUT} ({len(cases)} cases, {low} low-confidence first)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
