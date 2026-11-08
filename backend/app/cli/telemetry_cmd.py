"""`retrace telemetry prune` — delete old durable telemetry rows.

    python -m app.cli.retrace telemetry prune --dry-run
    python -m app.cli.retrace telemetry prune --days 30

Deletes `metric_events` rows older than N days (default TELEMETRY_RETENTION_DAYS)
in batches, committing each batch. Exit codes: 0 done, 2 error.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from app.core.config import get_settings
from app.db import session as db_session
from app.services.telemetry_retention import DEFAULT_BATCH_SIZE, prune_metric_events

EXIT_OK = 0
EXIT_ERROR = 2


def cmd_telemetry_prune(args: argparse.Namespace) -> int:
    days = args.days if args.days is not None else get_settings().telemetry_retention_days
    try:
        db_session.init_db()
        assert db_session.engine is not None
        with db_session.engine.connect() as conn:
            result = prune_metric_events(conn, days=days, dry_run=args.dry_run, batch_size=args.batch_size)
    except ValueError as exc:
        print(f"Prune error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - report any database failure as exit 2
        print(f"Prune error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(result.message())
    return EXIT_OK


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def register(sub: Any) -> None:
    tel = sub.add_parser("telemetry", help="Durable telemetry maintenance")
    tel_sub = tel.add_subparsers(dest="telemetry_command", required=True)
    prune = tel_sub.add_parser("prune", help="Delete metric_events older than N days, in batches")
    prune.add_argument(
        "--days",
        type=_positive_int,
        default=None,
        help="Keep the last N days (default: TELEMETRY_RETENTION_DAYS, 14)",
    )
    prune.add_argument("--dry-run", action="store_true", help="Only count the rows that would be deleted")
    prune.add_argument(
        "--batch-size",
        type=_positive_int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Rows per DELETE (default {DEFAULT_BATCH_SIZE})",
    )
    prune.set_defaults(func=cmd_telemetry_prune)
