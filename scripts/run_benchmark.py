#!/usr/bin/env python3
"""Run the planted-failure / gold offline benchmark and print a summary.

Usage (inside backend container):
  python /scripts/run_benchmark.py --suite planted_v1
"""

from __future__ import annotations

import argparse
import json
import sys

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from app.db import session as db_session
from app.services.eval.runner import run_suite_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Retrace Phase 5 benchmark")
    parser.add_argument("--suite", default="planted_v1")
    parser.add_argument("--suite-version", default="1.0.0")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    args = parser.parse_args()

    db_session.init_db()
    assert db_session.SessionLocal is not None
    db = db_session.SessionLocal()
    try:
        report = run_suite_benchmark(
            db,
            suite_id=args.suite,
            suite_version=args.suite_version,
            persist=True,
        )
    finally:
        db.close()

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    summary = report["summary"]
    print(f"suite: {report['suite_id']}@{report['suite_version']}")
    print(f"suite_hash: {report['suite_hash']}")
    print(f"experiment_id: {report['experiment_id']}")
    print(
        f"cases: {summary['total_cases']}  correct: {summary['correct']}  "
        f"incorrect: {summary['incorrect']}"
    )
    print(f"failure_code_accuracy: {summary['failure_code_accuracy']}")
    print(f"rule_accuracy: {summary['rule_accuracy']}")
    print(f"evidence_accuracy: {summary['evidence_accuracy']}")
    print("confusion_matrix labels:", summary["confusion_matrix"]["labels"])
    for row in report["cases"]:
        mark = "PASS" if row["correct"] else "FAIL"
        print(
            f"  [{mark}] {row['scenario_id']}: "
            f"expected={row['expected']['failure_code']} "
            f"predicted={row['predicted']['failure_code']} "
            f"rule={row['predicted']['rule_id']}"
        )
    if report.get("artifact_uri"):
        print(f"artifact: {report['artifact_uri']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
