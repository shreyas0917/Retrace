"""`retrace diagnose` — diagnose traces from your own RAG app, in process.

    python -m app.cli.retrace diagnose --file trace.json
    python -m app.cli.retrace diagnose --batch traces.jsonl --fail-on RETRIEVAL_MISS,GENERATION_CONTRADICTION
    python -m app.cli.retrace diagnose --file trace.json --json

Exit codes: 0 every trace diagnosed and none matched --fail-on; 1 at least one
diagnosed code is in --fail-on; 2 any trace failed to load, validate or
diagnose (errors win over --fail-on). `--fail-on ALL_FAILURES` matches every
code that is not an OK_* outcome.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.errors import AppError
from app.schemas.traces import TraceRequest
from app.services.external_traces import ingest_trace

EXIT_OK = 0
EXIT_FAIL_ON = 1
EXIT_ERROR = 2
ALL_FAILURES = "ALL_FAILURES"


def _verdict(code: str | None) -> str:
    if not code:
        return "not diagnosed"
    if code.startswith("OK_"):
        return "healthy"
    if code == "DIAGNOSIS_UNCERTAIN":
        return "uncertain"
    if code.startswith("EVAL_"):
        return "infrastructure"
    return "failure"


def _load_items(args: argparse.Namespace) -> list[Any]:
    """Raw trace objects; a malformed JSON Lines line becomes an error item."""
    if args.file:
        data = json.loads(Path(args.file).read_text(encoding="utf-8-sig"))
        return data if isinstance(data, list) else [data]
    items: list[Any] = []
    lines = Path(args.batch).read_text(encoding="utf-8-sig").splitlines()
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            items.append(ValueError(f"line {line_no}: invalid JSON ({exc.msg})"))
    return items


def _matches(code: str | None, fail_on: set[str]) -> bool:
    if not code or not fail_on:
        return False
    if ALL_FAILURES in fail_on and not code.startswith("OK_"):
        return True
    return code in fail_on


def diagnose_items(db, items: list[Any], fail_on: set[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for index, raw in enumerate(items):
        if isinstance(raw, Exception):
            results.append({"index": index, "ok": False, "error": str(raw)})
            continue
        try:
            req = TraceRequest.model_validate(raw)
        except ValidationError as exc:
            errors = "; ".join(f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors())
            results.append({"index": index, "ok": False, "error": f"invalid trace: {errors}"})
            continue
        # The CLI exists to diagnose, so a trace's own `diagnose: false` is ignored.
        req = req.model_copy(update={"diagnose": True})
        try:
            out = ingest_trace(db, req)
        except AppError as exc:
            db.rollback()
            results.append(
                {
                    "index": index,
                    "ok": False,
                    "execution_id": getattr(exc, "execution_id", None),
                    "error": f"{exc.code}: {exc.message}",
                }
            )
            continue
        code = (out.get("diagnosis") or {}).get("failure_code")
        results.append({"index": index, "ok": True, "matched_fail_on": _matches(code, fail_on), **out})

    errors = sum(1 for r in results if not r["ok"])
    matched = [r for r in results if r.get("matched_fail_on")]
    exit_code = EXIT_ERROR if errors else (EXIT_FAIL_ON if matched else EXIT_OK)
    return {
        "summary": {
            "total": len(results),
            "diagnosed": len(results) - errors,
            "errors": errors,
            "matched_fail_on": len(matched),
            "fail_on": sorted(fail_on),
        },
        "exit_code": exit_code,
        "results": results,
    }


def _print_human(report: dict[str, Any]) -> None:
    total = report["summary"]["total"]
    for r in report["results"]:
        head = f"[{r['index'] + 1}/{total}]"
        if not r["ok"]:
            print(f"{head} ERROR  {r['error']}")
            if r.get("execution_id"):
                print(f"         execution: {r['execution_id']} (stored, not diagnosed)")
            continue
        d = r.get("diagnosis") or {}
        code = d.get("failure_code")
        flag = "  <- matches --fail-on" if r.get("matched_fail_on") else ""
        print(f"{head} {_verdict(code).upper()}{flag}")
        print(f"         execution:      {r['execution_id']}")
        print(f"         failure code:   {code}")
        print(f"         rule:           {d.get('rule_id')}")
        calibrated = d.get("calibrated_confidence")
        conf = d.get("confidence") or "n/a"
        if calibrated is not None:
            conf += f" (calibrated {calibrated:.2f})"
        print(f"         confidence:     {conf}")
        if d.get("explanation"):
            print(f"         why:            {d['explanation']}")
        print(f"         recommendation: {d.get('recommendation_code') or 'NONE'}")
        for w in r.get("warnings") or []:
            print(f"         note:           {w}")
    s = report["summary"]
    print(
        f"\n{s['total']} trace(s): {s['diagnosed']} diagnosed, {s['errors']} error(s), "
        f"{s['matched_fail_on']} matched --fail-on. Exit {report['exit_code']}."
    )


def cmd_diagnose(args: argparse.Namespace) -> int:
    if bool(args.file) == bool(args.batch):
        print("diagnose: pass exactly one of --file or --batch", file=sys.stderr)
        return EXIT_ERROR
    fail_on = {c.strip().upper() for c in (args.fail_on or "").split(",") if c.strip()}
    try:
        items = _load_items(args)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"diagnose: cannot read input: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not items:
        print("diagnose: no traces found in input", file=sys.stderr)
        return EXIT_ERROR

    from app.db import session as db_session

    db_session.init_db()
    assert db_session.SessionLocal is not None
    db = db_session.SessionLocal()
    try:
        report = diagnose_items(db, items, fail_on)
    finally:
        db.close()

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human(report)
    return int(report["exit_code"])


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "diagnose",
        help="Diagnose traces from your own RAG app (exit 0 ok, 1 --fail-on matched, 2 error)",
    )
    p.add_argument("--file", help="A trace JSON object (or a JSON array of traces)")
    p.add_argument("--batch", help="A JSON Lines file, one trace per line")
    p.add_argument(
        "--fail-on",
        default="",
        help="Comma-separated failure codes that make the command exit 1 (or ALL_FAILURES)",
    )
    p.add_argument("--json", action="store_true", help="Print the full result as JSON")
    p.set_defaults(func=cmd_diagnose)
