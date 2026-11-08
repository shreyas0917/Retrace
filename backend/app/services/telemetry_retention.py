"""Telemetry retention: delete old `metric_events` rows in batches.

Used by `retrace telemetry prune` and, when TELEMETRY_PRUNE_ENABLED=true, by a
daily background task in the API process. With several workers every one of
them schedules the task, so it takes a Postgres advisory lock first and only
the worker that gets the lock prunes; the others skip that round.

Everything runs on one Connection: a session-level advisory lock belongs to
the connection that took it, and each batch is committed on its own so a long
prune never holds one huge transaction.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 5000
# Fixed key for pg_try_advisory_lock: the first 8 bytes of sha256("retrace.telemetry_prune"),
# as a signed 64-bit integer. Any constant works as long as nothing else uses it.
PRUNE_LOCK_KEY = 4415693627741623120

_COUNT_SQL = text("SELECT count(*) FROM metric_events WHERE ts < :cutoff")
_DELETE_BATCH_SQL = text(
    "DELETE FROM metric_events WHERE id IN "
    "(SELECT id FROM metric_events WHERE ts < :cutoff ORDER BY id LIMIT :batch_size)"
)


@dataclass(frozen=True)
class PruneResult:
    days: int
    cutoff: datetime
    dry_run: bool
    matched: int  # rows older than the cutoff when the prune started
    deleted: int  # rows actually deleted (0 for a dry run)
    batches: int  # DELETE statements that removed at least one row

    def message(self) -> str:
        when = self.cutoff.isoformat(timespec="seconds")
        if self.dry_run:
            return f"Would delete {self.matched} metric_events rows older than {self.days} days (before {when})."
        return (
            f"Deleted {self.deleted} metric_events rows older than {self.days} days "
            f"(before {when}) in {self.batches} batch{'es' if self.batches != 1 else ''}."
        )


def cutoff_for(days: int, now: datetime | None = None) -> datetime:
    if days < 1:
        raise ValueError("days must be at least 1")
    return (now or datetime.now(UTC)) - timedelta(days=days)


def prune_metric_events(
    conn: Connection,
    *,
    days: int,
    dry_run: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime | None = None,
) -> PruneResult:
    """Delete rows older than `days` in batches of `batch_size`, committing each batch."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    cutoff = cutoff_for(days, now)
    matched = int(conn.execute(_COUNT_SQL, {"cutoff": cutoff}).scalar_one())
    conn.commit()
    if dry_run:
        return PruneResult(days, cutoff, True, matched, 0, 0)

    deleted = 0
    batches = 0
    while True:
        removed = conn.execute(_DELETE_BATCH_SQL, {"cutoff": cutoff, "batch_size": batch_size}).rowcount
        conn.commit()
        if removed:
            deleted += removed
            batches += 1
        if removed < batch_size:
            break
    return PruneResult(days, cutoff, False, matched, deleted, batches)


def try_advisory_lock(conn: Connection) -> bool:
    got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": PRUNE_LOCK_KEY}).scalar_one())
    conn.commit()
    return got


def advisory_unlock(conn: Connection) -> None:
    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": PRUNE_LOCK_KEY})
    conn.commit()


def prune_with_lock(
    engine: Engine,
    *,
    days: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: datetime | None = None,
) -> PruneResult | None:
    """Prune if no other process holds the prune lock; return None when skipped."""
    with engine.connect() as conn:
        if not try_advisory_lock(conn):
            logger.info("telemetry_prune_skipped", reason="lock_held")
            return None
        try:
            result = prune_metric_events(conn, days=days, batch_size=batch_size, now=now)
        finally:
            advisory_unlock(conn)
    logger.info(
        "telemetry_pruned",
        days=result.days,
        deleted=result.deleted,
        batches=result.batches,
        cutoff=result.cutoff.isoformat(),
    )
    return result


async def run_daily_prune(interval_seconds: float) -> None:
    """Background loop for the API process: prune now, then every `interval_seconds`.

    Errors are logged and never stop the loop; cancellation ends it.
    """
    from app.core.config import get_settings
    from app.db import session as db_session

    while True:
        try:
            settings = get_settings()
            if db_session.engine is not None:
                await asyncio.to_thread(prune_with_lock, db_session.engine, days=settings.telemetry_retention_days)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a failed prune must not take the API down
            logger.warning("telemetry_prune_failed", error=str(exc)[:300])
        await asyncio.sleep(interval_seconds)
