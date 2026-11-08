"""Telemetry retention: `retrace telemetry prune` and the locked daily prune.

Every test dates its rows around 1900 and prunes against a fixed `now` (or a
100-year window), so a run against a developer database never touches real
telemetry.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.cli.retrace import main as cli_main
from app.db import session as db_session
from app.db.models import MetricEvent
from app.services import telemetry_retention as tr

NOW = datetime(1901, 1, 1, tzinfo=UTC)


@pytest.fixture
def engine():
    db_session.init_db()
    assert db_session.engine is not None
    return db_session.engine


@pytest.fixture
def marker(engine):
    """A unique metric name for this test's rows; leftovers are removed afterwards."""
    name = f"test.retention.{uuid.uuid4().hex[:10]}"
    yield name
    with db_session.SessionLocal() as db:
        db.query(MetricEvent).filter(MetricEvent.name == name).delete()
        db.commit()


def _insert(name: str, timestamps: list[datetime]) -> None:
    with db_session.SessionLocal() as db:
        db.add_all(MetricEvent(ts=ts, kind="counter", name=name, value=1.0) for ts in timestamps)
        db.commit()


def _count(name: str) -> int:
    with db_session.SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(MetricEvent).where(MetricEvent.name == name)))


def _old(n: int) -> list[datetime]:
    """n timestamps 30 to 30+n days before NOW: older than a 14-day retention."""
    return [NOW - timedelta(days=30 + i) for i in range(n)]


def _recent(n: int) -> list[datetime]:
    return [NOW - timedelta(days=1, minutes=i) for i in range(n)]


def test_retention_settings_defaults(monkeypatch) -> None:
    from app.core.config import get_settings

    for var in ("TELEMETRY_RETENTION_DAYS", "TELEMETRY_PRUNE_ENABLED", "TELEMETRY_PRUNE_INTERVAL_SECONDS"):
        monkeypatch.delenv(var, raising=False)
    s = get_settings()
    assert s.telemetry_retention_days == 14
    assert s.telemetry_prune_enabled is False
    assert s.telemetry_prune_interval_seconds == 86400


def test_dry_run_counts_and_deletes_nothing(engine, marker) -> None:
    _insert(marker, _old(4) + _recent(3))
    with engine.connect() as conn:
        result = tr.prune_metric_events(conn, days=14, dry_run=True, now=NOW)
    assert result.dry_run and result.matched >= 4 and result.deleted == 0 and result.batches == 0
    assert _count(marker) == 7
    assert result.message().startswith(f"Would delete {result.matched} metric_events rows older than 14 days")


def test_prune_deletes_only_rows_past_the_cutoff(engine, marker) -> None:
    _insert(marker, _old(4) + _recent(3))
    with engine.connect() as conn:
        result = tr.prune_metric_events(conn, days=14, now=NOW)
    assert result.cutoff == NOW - timedelta(days=14)
    assert _count(marker) == 3  # the recent rows stay
    assert result.deleted >= 4


@pytest.mark.parametrize(
    ("old_rows", "batch_size", "batches"),
    [
        (6, 3, 2),  # exact multiple: two full batches, then an empty one that is not counted
        (7, 3, 3),  # remainder: two full batches and one partial
        (2, 3, 1),  # fewer rows than one batch
        (0, 3, 0),  # nothing to delete
    ],
)
def test_batch_boundaries(engine, marker, old_rows, batch_size, batches) -> None:
    # A cutoff just after this test's rows, so only its own rows can match.
    now = datetime(1900, 6, 1, tzinfo=UTC)
    stamps = [datetime(1900, 1, 1, tzinfo=UTC) + timedelta(hours=i) for i in range(old_rows)]
    _insert(marker, stamps + [now - timedelta(hours=1)])
    with engine.connect() as conn:
        result = tr.prune_metric_events(conn, days=30, batch_size=batch_size, now=now)
    assert (result.matched, result.deleted, result.batches) == (old_rows, old_rows, batches)
    assert _count(marker) == 1


def test_default_batch_size_is_5000() -> None:
    assert tr.DEFAULT_BATCH_SIZE == 5000


def test_invalid_arguments_are_rejected(engine) -> None:
    with engine.connect() as conn:
        with pytest.raises(ValueError):
            tr.prune_metric_events(conn, days=0, now=NOW)
        with pytest.raises(ValueError):
            tr.prune_metric_events(conn, days=14, batch_size=0, now=NOW)


def test_lock_contention_skips_the_second_worker(engine, marker) -> None:
    _insert(marker, _old(2))
    with engine.connect() as holder:
        assert tr.try_advisory_lock(holder)
        try:
            assert tr.prune_with_lock(engine, days=14, now=NOW) is None
            assert _count(marker) == 2  # the skipped worker deleted nothing
        finally:
            tr.advisory_unlock(holder)
    result = tr.prune_with_lock(engine, days=14, now=NOW)
    assert result is not None and result.deleted >= 2
    assert _count(marker) == 0


def test_lock_is_released_after_a_prune(engine) -> None:
    assert tr.prune_with_lock(engine, days=14, now=NOW) is not None
    with engine.connect() as conn:
        assert tr.try_advisory_lock(conn)
        tr.advisory_unlock(conn)


def test_lock_is_released_when_the_prune_fails(engine, monkeypatch) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("db went away")

    monkeypatch.setattr(tr, "prune_metric_events", boom)
    with pytest.raises(RuntimeError):
        tr.prune_with_lock(engine, days=14, now=NOW)
    with engine.connect() as conn:
        assert tr.try_advisory_lock(conn)
        tr.advisory_unlock(conn)


def test_daily_loop_survives_errors_and_stops_on_cancel(engine, monkeypatch) -> None:
    calls: list[int] = []

    def fake_prune(_engine, *, days):
        calls.append(days)
        if len(calls) == 1:
            raise RuntimeError("first round fails")
        return None

    monkeypatch.setattr(tr, "prune_with_lock", fake_prune)
    monkeypatch.setenv("TELEMETRY_RETENTION_DAYS", "21")

    async def run() -> None:
        task = asyncio.create_task(tr.run_daily_prune(0.01))
        while len(calls) < 3:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert calls[:3] == [21, 21, 21]


def test_cli_dry_run_and_prune(engine, marker, capsys) -> None:
    # 100-year retention: only rows from before ~1926 can match, i.e. this test's.
    _insert(marker, [datetime(1900, 1, 1, tzinfo=UTC)] * 3)
    assert cli_main(["telemetry", "prune", "--days", "36500", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Would delete" in out and "older than 36500 days" in out
    assert _count(marker) == 3

    assert cli_main(["telemetry", "prune", "--days", "36500", "--batch-size", "2"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Deleted ") and "in 2 batches" in out
    assert _count(marker) == 0


def test_cli_rejects_non_positive_days(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli_main(["telemetry", "prune", "--days", "0"])
    assert exc.value.code == 2
