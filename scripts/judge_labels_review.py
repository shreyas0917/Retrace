#!/usr/bin/env python3
"""Human review of the AI-drafted judge labels (judge_labels_v1).

The 66 judge examples were drafted by an AI agent. This tool lets the
project author review every label before the labels are used for anything,
and records the outcome honestly.

    python scripts/judge_labels_review.py export            # write the sheet
    python scripts/judge_labels_review.py apply --dry-run   # preview corrections
    python scripts/judge_labels_review.py apply             # merge corrections

The sheet has one row per labelled unit (a chunk's relevance, a claim's
support, an example's context sufficiency, faithfulness band or contradiction
verdict), so the number of changed labels is an exact count. Leave the
`correction` column empty to keep the current label.

`apply` sets every example's annotator to "ai_draft_author_reviewed", stores
the review date, recomputes the manifest hash and label counts, and records
how many labels the author changed. It refuses a sheet that no longer matches
the dataset. Stdlib only, so it runs on the host without the backend image.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "backend" / "datasets" / "judges" / "judge_labels_v1.jsonl"
DEFAULT_MANIFEST = ROOT / "backend" / "datasets" / "judges" / "manifest.json"
DEFAULT_SHEET = ROOT / "data" / "labelling" / "judge_labels_v1_review.csv"

COLUMNS = [
    "row_id",
    "example_id",
    "judge",
    "what_to_judge",
    "input",
    "current_label",
    "correction",
    "notes",
]

REVIEWED_ANNOTATOR = "ai_draft_author_reviewed"
REVIEWED_SOURCE = (
    "AI-drafted, reviewed and corrected by the author. Drafted by an AI agent from "
    "data/corpus/demo facts, then every label was checked by the project author "
    "(see the review block for how many were changed). Chunk texts are excerpts of "
    "the corpus documents (plus 4 synthetic injection chunks under the 'injected' "
    "document id); chunk ordinals are illustrative."
)

AI_REVIEWED_ANNOTATOR = "ai_draft_blind"
AI_REVIEWED_SOURCE = (
    "AI-drafted, cross-checked by a second independent AI ({changed} of {units} changed); not reviewed by a "
    "human. The second AI saw only the review sheet (data/labelling/judge_labels_v1_review.ai_draft.csv). "
    "Drafted by an AI agent from data/corpus/demo facts. Chunk texts are excerpts of the corpus documents (plus 4 synthetic "
    "injection chunks under the 'injected' document id); chunk ordinals are illustrative."
)
# annotator -> (source text, who reviewed)
ANNOTATORS = {
    REVIEWED_ANNOTATOR: (REVIEWED_SOURCE, "author"),
    AI_REVIEWED_ANNOTATOR: (AI_REVIEWED_SOURCE, "ai_agent_blind"),
}

ASK = {
    "chunk": "Is this chunk relevant to the question? (true/false)",
    "context_sufficient": (
        "Do the chunks, taken together, contain enough information to answer the " "question? (true/false)"
    ),
    "claim": "Is this claim supported by the context? (true/false)",
    "faithfulness_band": (
        "Acceptable faithfulness score range, written lo-hi (for example 0.5-0.5). "
        "It should contain supported claims divided by total claims."
    ),
    "contradicts": (
        "Does the answer contradict the context? Missing or extra information is " "not a contradiction. (true/false)"
    ),
}

TRUE_WORDS = {"true", "t", "yes", "y", "1"}
FALSE_WORDS = {"false", "f", "no", "n", "0"}


class ReviewError(Exception):
    """Raised for a stale sheet or an unparseable correction."""


# --------------------------------------------------------------------------
# dataset io + hashing (mirrors app.services.eval.suite_loader)
# --------------------------------------------------------------------------
def canonical_hash(lines: list[str]) -> str:
    out = [
        json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for line in lines
        if line.strip()
    ]
    payload = "\n".join(out) + ("\n" if out else "")
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_rows(path: Path, rows: list[dict[str, Any]]) -> list[str]:
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


# --------------------------------------------------------------------------
# units
# --------------------------------------------------------------------------
def _fmt_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _fmt_band(band: list[float]) -> str:
    return f"{float(band[0]):g}-{float(band[1]):g}"


def _context(row: dict[str, Any]) -> str:
    return "\n\n".join(f"CHUNK {c.get('chunk_id', '?')}:\n{c.get('text', '')}" for c in row.get("chunks", []))


def iter_units(rows: list[dict[str, Any]]):
    """Yield (row_id, example index, kind, key, sheet fields) for every label."""
    for idx, row in enumerate(rows):
        ex = row["example_id"]
        judge = row["judge"]
        question = f"QUESTION: {row.get('query', '')}"
        if judge == "relevance":
            for i, chunk in enumerate(row.get("chunks", [])):
                yield (
                    f"{ex}#chunk-{i + 1}",
                    idx,
                    "chunk",
                    i,
                    {
                        "what_to_judge": ASK["chunk"],
                        "input": f"{question}\n\nCHUNK {chunk.get('chunk_id', '?')}:\n{chunk.get('text', '')}",
                        "current_label": _fmt_bool(chunk.get("relevant")),
                    },
                )
            yield (
                f"{ex}#context_sufficient",
                idx,
                "context_sufficient",
                None,
                {
                    "what_to_judge": ASK["context_sufficient"],
                    "input": f"{question}\n\n{_context(row)}",
                    "current_label": _fmt_bool(row.get("context_sufficient")),
                },
            )
        elif judge == "faithfulness":
            answer = f"ANSWER: {row.get('answer', '')}"
            for j, claim in enumerate(row.get("claims", [])):
                yield (
                    f"{ex}#claim-{j + 1}",
                    idx,
                    "claim",
                    j,
                    {
                        "what_to_judge": ASK["claim"],
                        "input": f"{question}\n{answer}\nCLAIM: {claim.get('claim', '')}\n\nCONTEXT:\n{_context(row)}",
                        "current_label": _fmt_bool(claim.get("supported")),
                    },
                )
            claims = "\n".join(f"- {c.get('claim', '')}" for c in row.get("claims", []))
            yield (
                f"{ex}#faithfulness_band",
                idx,
                "faithfulness_band",
                None,
                {
                    "what_to_judge": ASK["faithfulness_band"],
                    "input": f"{question}\n{answer}\nCLAIMS:\n{claims}\n\nCONTEXT:\n{_context(row)}",
                    "current_label": _fmt_band(row.get("faithfulness_band", [0, 0])),
                },
            )
        elif judge == "contradiction":
            yield (
                f"{ex}#contradicts",
                idx,
                "contradicts",
                None,
                {
                    "what_to_judge": ASK["contradicts"],
                    "input": f"{question}\nANSWER: {row.get('answer', '')}\n\nCONTEXT:\n{_context(row)}",
                    "current_label": _fmt_bool(row.get("contradicts")),
                },
            )
        else:
            raise ReviewError(f"{ex}: unknown judge type {judge!r}")


def _parse_bool(text: str, row_id: str) -> bool:
    word = text.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise ReviewError(f"{row_id}: correction {text!r} is not true/false")


def _parse_band(text: str, row_id: str) -> list[float]:
    raw = text.strip().replace(",", "-").replace(" ", "")
    parts = [p for p in raw.split("-") if p != ""]
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise ReviewError(f"{row_id}: correction {text!r} is not a lo-hi range") from exc
    if len(values) == 1:
        values = values * 2
    if len(values) != 2 or not 0.0 <= values[0] <= values[1] <= 1.0:
        raise ReviewError(f"{row_id}: correction {text!r} must be lo-hi with 0 <= lo <= hi <= 1")
    return values


def _current(row: dict[str, Any], kind: str, key: Any) -> Any:
    if kind == "chunk":
        return bool(row["chunks"][key].get("relevant"))
    if kind == "claim":
        return bool(row["claims"][key].get("supported"))
    if kind == "faithfulness_band":
        return [float(x) for x in row.get("faithfulness_band", [0, 0])]
    return bool(row.get(kind))


def _set(row: dict[str, Any], kind: str, key: Any, value: Any) -> None:
    if kind == "chunk":
        row["chunks"][key]["relevant"] = value
    elif kind == "claim":
        row["claims"][key]["supported"] = value
    else:
        row[kind] = value


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def export_sheet(dataset: Path, sheet: Path, *, force: bool = False) -> int:
    if sheet.exists() and not force:
        with sheet.open(encoding="utf-8-sig", newline="") as fh:
            filled = any((r.get("correction") or r.get("notes") or "").strip() for r in csv.DictReader(fh))
        if filled:
            raise ReviewError(f"{sheet} already contains corrections; refusing to overwrite (use --force)")
    rows = load_rows(dataset)
    sheet.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    # utf-8-sig so spreadsheet apps detect the encoding.
    with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row_id, idx, _kind, _key, fields in iter_units(rows):
            writer.writerow(
                {
                    "row_id": row_id,
                    "example_id": rows[idx]["example_id"],
                    "judge": rows[idx]["judge"],
                    **fields,
                    "correction": "",
                    "notes": "",
                }
            )
            count += 1
    return count


def label_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    rel = [r for r in rows if r["judge"] == "relevance"]
    fai = [r for r in rows if r["judge"] == "faithfulness"]
    con = [r for r in rows if r["judge"] == "contradiction"]
    return {
        "relevance_chunks_total": sum(len(r.get("chunks", [])) for r in rel),
        "relevance_chunks_relevant": sum(1 for r in rel for c in r.get("chunks", []) if c.get("relevant")),
        "relevance_context_sufficient_true": sum(1 for r in rel if r.get("context_sufficient")),
        "faithfulness_fully_supported": sum(
            1 for r in fai if r.get("claims") and all(c.get("supported") for c in r["claims"])
        ),
        "faithfulness_with_unsupported": sum(
            1 for r in fai if any(not c.get("supported") for c in r.get("claims", []))
        ),
        "contradiction_true": sum(1 for r in con if r.get("contradicts")),
        "contradiction_false": sum(1 for r in con if not r.get("contradicts")),
    }


def band_warnings(rows: list[dict[str, Any]]) -> list[str]:
    out = []
    for r in rows:
        if r["judge"] != "faithfulness" or not r.get("claims"):
            continue
        ratio = sum(1 for c in r["claims"] if c.get("supported")) / len(r["claims"])
        lo, hi = r.get("faithfulness_band", [0, 0])
        if not lo - 1e-9 <= ratio <= hi + 1e-9:
            out.append(
                f"{r['example_id']}: supported/total = {ratio:.2f} is outside the band "
                f"{_fmt_band([lo, hi])}; correct the band too"
            )
    return out


def apply_sheet(
    dataset: Path,
    manifest_path: Path,
    sheet: Path,
    *,
    review_date: str,
    dry_run: bool = False,
    annotator: str = REVIEWED_ANNOTATOR,
) -> dict[str, Any]:
    if annotator not in ANNOTATORS:
        raise ReviewError(f"unknown annotator {annotator!r}; use one of {sorted(ANNOTATORS)}")
    source, reviewed_by = ANNOTATORS[annotator]
    rows = load_rows(dataset)
    units = {row_id: (idx, kind, key) for row_id, idx, kind, key, _ in iter_units(rows)}

    with sheet.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ReviewError(f"sheet is missing columns: {missing}")
        sheet_rows = list(reader)

    sheet_ids = [r["row_id"] for r in sheet_rows]
    if len(set(sheet_ids)) != len(sheet_ids):
        raise ReviewError("sheet has duplicate row_id values")
    if set(sheet_ids) != set(units):
        extra = sorted(set(sheet_ids) - set(units))[:5]
        absent = sorted(set(units) - set(sheet_ids))[:5]
        raise ReviewError(f"sheet does not match the dataset (stale?): unknown rows {extra}, missing rows {absent}")

    changes: list[dict[str, Any]] = []
    notes: list[dict[str, str]] = []
    for srow in sheet_rows:
        row_id = srow["row_id"]
        idx, kind, key = units[row_id]
        if (srow.get("notes") or "").strip():
            notes.append({"row_id": row_id, "note": srow["notes"].strip()})
        text = (srow.get("correction") or "").strip()
        if not text:
            continue
        new = _parse_band(text, row_id) if kind == "faithfulness_band" else _parse_bool(text, row_id)
        old = _current(rows[idx], kind, key)
        if new != old:
            _set(rows[idx], kind, key, new)
            changes.append({"row_id": row_id, "old": old, "new": new})

    for r in rows:
        r["annotator"] = annotator
        r["review_date"] = review_date

    summary = {
        "reviewed_units": len(units),
        "changed_labels": len(changes),
        "changes": changes,
        "notes": notes,
        "band_warnings": band_warnings(rows),
    }
    if dry_run:
        return summary

    lines = write_rows(dataset, rows)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dataset_hash"] = canonical_hash(lines)
    manifest["annotator"] = annotator
    manifest["source"] = source.format(changed=len(changes), units=len(units))
    manifest.pop("provisional", None)
    manifest["human_reviewed"] = annotator == REVIEWED_ANNOTATOR
    manifest["label_counts"] = label_counts(rows)
    manifest["review"] = {
        "reviewed_by": reviewed_by,
        "review_date": review_date,
        "reviewed_units": len(units),
        "changed_labels": len(changes),
        "sheet": sheet.name,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary["dataset_hash"] = manifest["dataset_hash"]
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    exp = sub.add_parser("export", help="write the review sheet")
    exp.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    exp.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    exp.add_argument("--force", action="store_true", help="overwrite a sheet that has corrections")
    app = sub.add_parser("apply", help="merge reviewed corrections into the dataset")
    app.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    app.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    app.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    app.add_argument("--date", default=dt.date.today().isoformat())
    app.add_argument("--dry-run", action="store_true")
    app.add_argument(
        "--annotator",
        default=REVIEWED_ANNOTATOR,
        choices=sorted(ANNOTATORS),
        help="ai_draft_author_reviewed (the author reviewed the sheet) or ai_draft_blind (a second AI agent did)",
    )
    args = parser.parse_args(argv)

    try:
        if args.cmd == "export":
            n = export_sheet(args.dataset, args.sheet, force=args.force)
            print(f"wrote {n} label rows to {args.sheet}")
            return 0
        summary = apply_sheet(
            args.dataset,
            args.manifest,
            args.sheet,
            review_date=args.date,
            dry_run=args.dry_run,
            annotator=args.annotator,
        )
    except ReviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verb = "would change" if args.dry_run else "changed"
    print(f"reviewed {summary['reviewed_units']} labels; {verb} {summary['changed_labels']}")
    for c in summary["changes"]:
        print(f"  {c['row_id']}: {c['old']} -> {c['new']}")
    for n in summary["notes"]:
        print(f"  note {n['row_id']}: {n['note']}")
    for w in summary["band_warnings"]:
        print(f"  warning: {w}")
    if not args.dry_run:
        print(f"dataset hash {summary['dataset_hash']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
