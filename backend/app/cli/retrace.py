"""Retrace CLI — `python -m app.cli.retrace …`"""

from __future__ import annotations

import argparse
import sys

from app.core.errors import NotFoundError
from app.db import session as db_session
from app.services.eval.baseline import BaselineError, baseline_to_dict, promote_baseline
from app.services.eval.evaluate import (
    EXIT_ERROR,
    EXIT_PASS,
    EvalIntegrityError,
    format_eval_report,
    run_evaluation,
)
from app.services.eval.suite_loader import SuiteValidationError
from app.services.eval.thresholds_config import ThresholdConfigError, load_thresholds


def _open_db():
    db_session.init_db()
    assert db_session.SessionLocal is not None
    return db_session.SessionLocal()


def cmd_eval(args: argparse.Namespace) -> int:
    db = _open_db()
    try:
        result = run_evaluation(
            db,
            suite_id=args.suite,
            suite_version=args.suite_version,
            expect_hash=args.expect_hash,
            thresholds_path=args.thresholds,
            persist=True,
        )
        print(format_eval_report(result))
        return int(result["exit_code"])
    except (SuiteValidationError, EvalIntegrityError, ThresholdConfigError) as exc:
        print(f"Evaluation error: {exc.message}", file=sys.stderr)
        if getattr(exc, "details", None):
            for k, v in exc.details.items():
                print(f"  {k}: {v}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001
        print(f"Evaluation error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        db.close()


def cmd_baseline_promote(args: argparse.Namespace) -> int:
    db = _open_db()
    try:
        thresholds = load_thresholds(args.thresholds) if args.thresholds else None
        row = promote_baseline(
            db,
            experiment_id=args.experiment_id,
            thresholds=thresholds,
            name=args.name,
        )
        data = baseline_to_dict(row)
        print("Baseline promoted")
        print(f"  baseline_id:   {data['baseline_id']}")
        print(f"  experiment_id: {data['experiment_id']}")
        print(f"  suite:         {data['suite_id']}@{data['suite_version']}")
        print(f"  suite_hash:    {data['suite_hash']}")
        print(f"  is_active:     {data['is_active']}")
        metrics = data["metrics"]
        print(
            "  metrics:       "
            f"failure_code={metrics.get('failure_code_accuracy')} "
            f"rule={metrics.get('rule_accuracy')} "
            f"evidence={metrics.get('evidence_accuracy')}"
        )
        return EXIT_PASS
    except (BaselineError, NotFoundError, SuiteValidationError, ThresholdConfigError) as exc:
        msg = getattr(exc, "message", str(exc))
        print(f"Baseline error: {msg}", file=sys.stderr)
        if getattr(exc, "details", None):
            for k, v in exc.details.items():
                print(f"  {k}: {v}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001
        print(f"Baseline error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retrace",
        description="Retrace evaluation and baseline CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    eval_p = sub.add_parser("eval", help="Run suite evaluation and gate against baseline")
    eval_p.add_argument("--suite", required=True, help="Suite id (e.g. gold_v1)")
    eval_p.add_argument("--suite-version", default="1.0.0")
    eval_p.add_argument(
        "--expect-hash",
        default=None,
        help="Optional expected suite sha256:... (exit 2 on mismatch)",
    )
    eval_p.add_argument(
        "--thresholds",
        default=None,
        help="Path to acceptance thresholds YAML",
    )
    eval_p.set_defaults(func=cmd_eval)

    base_p = sub.add_parser("baseline", help="Baseline operations")
    base_sub = base_p.add_subparsers(dest="baseline_command", required=True)
    promote_p = base_sub.add_parser("promote", help="Promote experiment to active baseline")
    promote_p.add_argument("experiment_id")
    promote_p.add_argument("--name", default=None)
    promote_p.add_argument("--thresholds", default=None)
    promote_p.set_defaults(func=cmd_baseline_promote)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
