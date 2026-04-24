"""Read-only SQL helpers for the daily report.

All queries accept an explicit UTC window as ISO-8601 Z strings. SQLite
compares those strings lexically, which matches chronological order for
Zulu timestamps — no re-parsing needed, no timezone library on the
critical path.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable


def utc_day_window(day: date) -> tuple[str, str]:
    """Return the ISO-8601 Z bounds for one UTC day.

    Half-open: `[day 00:00:00Z, day+1 00:00:00Z)`. The half-open shape keeps
    two consecutive days from double-counting the midnight tick.
    """
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), end.strftime(fmt)


def previous_utc_day(now: datetime | None = None) -> date:
    """The UTC day to report on — i.e. yesterday, wall-clock UTC.

    Called with a `now` argument in tests so we don't depend on the system
    clock. In production the timer fires at 02:30 UTC so `datetime.now` on
    the VM and `date.today()` give the same answer, but the tests need to
    travel in time.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now.astimezone(timezone.utc).date() - timedelta(days=1))


def fetch_measurements_in_window(
    db_path: Path | str,
    start_iso: str,
    end_iso: str,
) -> list[dict]:
    """Return every measurement row with `start_iso <= timestamp < end_iso`.

    One query, all nodes — the per-node bucketing happens in pure Python
    so `aggregation.py` stays decoupled from SQLite.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            "SELECT timestamp, node_url, success, latency_ms, "
            "       block_height, error_message "
            "  FROM measurements "
            " WHERE timestamp >= ? AND timestamp < ? "
            " ORDER BY node_url, timestamp",
            (start_iso, end_iso),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def group_by_node(rows: Iterable[dict]) -> dict[str, list[dict]]:
    """Bucket measurement rows by `node_url`, preserving input order inside buckets."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["node_url"], []).append(r)
    return out
