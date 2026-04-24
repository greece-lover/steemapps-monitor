"""Database round-trip tests.

Uses a temporary SQLite file per test so we never touch the live data/
directory. The test also proves the schema survives being applied twice
(the monitor calls `initialise()` on every boot).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import database
from database import (
    Measurement,
    initialise,
    insert_measurement,
    get_recent_measurements,
    get_latest_per_node,
    get_uptime_stats,
    row_count,
    sync_nodes,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.sqlite"
    initialise(p)
    return p


def _make(ts: str, url: str, ok: bool = True, latency: int | None = 150,
          height: int | None = 1000, err: str | None = None) -> Measurement:
    return Measurement(
        timestamp=ts, node_url=url, success=ok,
        latency_ms=latency, block_height=height,
        error_message=err, source_location="test",
    )


def test_initialise_is_idempotent(tmp_path: Path):
    p = tmp_path / "x.sqlite"
    initialise(p)
    initialise(p)  # must not throw
    assert p.exists()


def test_insert_and_read_round_trip(db_path: Path):
    m = _make("2026-04-24T10:00:00Z", "https://a.example")
    rowid = insert_measurement(m, db_path)
    assert rowid > 0

    rows = get_recent_measurements(limit=10, db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["node_url"] == "https://a.example"
    assert rows[0]["success"] == 1
    assert rows[0]["latency_ms"] == 150
    assert rows[0]["block_height"] == 1000
    assert rows[0]["source_location"] == "test"


def test_filter_by_node_url(db_path: Path):
    insert_measurement(_make("2026-04-24T10:00:00Z", "https://a.example"), db_path)
    insert_measurement(_make("2026-04-24T10:00:01Z", "https://b.example"), db_path)
    insert_measurement(_make("2026-04-24T10:00:02Z", "https://a.example"), db_path)

    a_rows = get_recent_measurements("https://a.example", db_path=db_path)
    b_rows = get_recent_measurements("https://b.example", db_path=db_path)
    assert len(a_rows) == 2
    assert len(b_rows) == 1


def test_get_latest_per_node_returns_newest_only(db_path: Path):
    insert_measurement(_make("2026-04-24T10:00:00Z", "https://a.example", height=1000), db_path)
    insert_measurement(_make("2026-04-24T10:01:00Z", "https://a.example", height=1020), db_path)
    insert_measurement(_make("2026-04-24T10:00:30Z", "https://b.example", height=1010), db_path)

    latest = get_latest_per_node(db_path)
    assert set(latest.keys()) == {"https://a.example", "https://b.example"}
    assert latest["https://a.example"]["block_height"] == 1020


def test_uptime_stats_counts_success_vs_total(db_path: Path):
    # 6 successes + 4 failures = 60 % uptime. Timestamps are in the last
    # minute so the 60-min lookback window covers them.
    base = "2026-04-24T10:00:"
    for i in range(6):
        insert_measurement(_make(f"{base}{i:02d}Z", "https://a.example"), db_path)
    for i in range(4):
        insert_measurement(_make(f"{base}{10 + i:02d}Z", "https://a.example",
                                 ok=False, latency=None, height=None,
                                 err="timeout"), db_path)
    # The in-window calculation depends on wall clock vs stored ts; we
    # can't assert 60 % exactly without time-travel. What we *can* check:
    # total returned, regardless of lookback, is at least the rows we wrote
    # or zero (if the test machine's clock skews more than the lookback
    # from the fake timestamps).
    stats = get_uptime_stats("https://a.example", lookback_minutes=60 * 24 * 365 * 10,
                             db_path=db_path)
    assert stats["total"] == 10
    assert stats["ok"] == 6
    assert stats["uptime_pct"] == 60.0


def test_row_count_reflects_inserts(db_path: Path):
    assert row_count(db_path) == 0
    insert_measurement(_make("2026-04-24T10:00:00Z", "https://a.example"), db_path)
    assert row_count(db_path) == 1


def test_sync_nodes_marks_dropped_as_inactive(db_path: Path):
    sync_nodes([
        {"url": "https://a.example", "region": "us"},
        {"url": "https://b.example", "region": "eu"},
    ], db_path)
    # Now drop b.
    sync_nodes([{"url": "https://a.example", "region": "us"}], db_path)
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = {r["url"]: r["active"] for r in conn.execute("SELECT url, active FROM nodes")}
    conn.close()
    assert rows == {"https://a.example": 1, "https://b.example": 0}
