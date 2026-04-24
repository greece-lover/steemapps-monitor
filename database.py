"""SQLite persistence layer for the Steem API monitor.

Single-writer, many-reader pattern: the monitor process inserts rows, the
FastAPI process (currently running in the same event loop) reads them. WAL
mode keeps readers off the writer's path. Callers are expected to open one
connection per operation; sqlite3's connection is not safe to share across
threads without `check_same_thread=False`, and the cost of reopening a
connection against a local file is negligible.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from config import DB_PATH, DATA_DIR


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    url         TEXT PRIMARY KEY,
    region      TEXT,
    added_at    TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS measurements (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT    NOT NULL,
    node_url         TEXT    NOT NULL,
    success          INTEGER NOT NULL,
    latency_ms       INTEGER,
    block_height     INTEGER,
    error_message    TEXT,
    source_location  TEXT
);

CREATE INDEX IF NOT EXISTS idx_measurements_timestamp
    ON measurements (timestamp);
CREATE INDEX IF NOT EXISTS idx_measurements_node_url
    ON measurements (node_url);
CREATE INDEX IF NOT EXISTS idx_measurements_node_ts
    ON measurements (node_url, timestamp);
"""


@dataclass
class Measurement:
    timestamp: str
    node_url: str
    success: bool
    latency_ms: Optional[int]
    block_height: Optional[int]
    error_message: Optional[str]
    source_location: str


def _utcnow_iso() -> str:
    # Always second-precision UTC; the methodology doc pins tick timestamps
    # to the 60 s boundary, so sub-second precision would be noise.
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def connect(db_path: Path | str = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Yield a configured SQLite connection. Commits on clean exit, rolls back on error."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        conn.close()


def initialise(db_path: Path | str = DB_PATH) -> None:
    """Create the schema if it doesn't exist. Idempotent."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def sync_nodes(nodes: list[dict], db_path: Path | str = DB_PATH) -> None:
    """Upsert the configured nodes into the `nodes` table.

    Nodes present in the table but missing from the config are marked
    inactive, not deleted — their historical measurements stay joinable.
    """
    urls_in_config = {n["url"] for n in nodes}
    now = _utcnow_iso()
    with connect(db_path) as conn:
        for n in nodes:
            conn.execute(
                "INSERT INTO nodes(url, region, added_at, active) VALUES(?, ?, ?, 1) "
                "ON CONFLICT(url) DO UPDATE SET region=excluded.region, active=1",
                (n["url"], n.get("region"), now),
            )
        # Mark drops.
        existing = conn.execute("SELECT url FROM nodes").fetchall()
        for row in existing:
            if row["url"] not in urls_in_config:
                conn.execute("UPDATE nodes SET active=0 WHERE url=?", (row["url"],))


def insert_measurement(m: Measurement, db_path: Path | str = DB_PATH) -> int:
    """Insert one measurement row and return its rowid."""
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO measurements "
            "(timestamp, node_url, success, latency_ms, block_height, error_message, source_location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                m.timestamp,
                m.node_url,
                1 if m.success else 0,
                m.latency_ms,
                m.block_height,
                m.error_message,
                m.source_location,
            ),
        )
        return int(cur.lastrowid or 0)


def get_recent_measurements(
    node_url: Optional[str] = None,
    limit: int = 100,
    db_path: Path | str = DB_PATH,
) -> list[dict]:
    """Return the most recent measurements, newest first. Optionally filtered per node."""
    with connect(db_path) as conn:
        if node_url is None:
            rows = conn.execute(
                "SELECT * FROM measurements ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM measurements WHERE node_url=? ORDER BY id DESC LIMIT ?",
                (node_url, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def get_latest_per_node(db_path: Path | str = DB_PATH) -> dict[str, dict]:
    """Return the most recent measurement for each known node, keyed by URL.

    Used by the `/api/v1/status` endpoint and by the scoring module to pick
    a chain-height reference.
    """
    sql = """
    SELECT m.*
      FROM measurements m
      INNER JOIN (
          SELECT node_url, MAX(id) AS max_id
            FROM measurements
           GROUP BY node_url
      ) mx ON m.id = mx.max_id
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    return {r["node_url"]: dict(r) for r in rows}


def get_uptime_stats(
    node_url: str,
    lookback_minutes: int = 60,
    db_path: Path | str = DB_PATH,
) -> dict:
    """Return counts of total / successful measurements for a node within the window.

    The window is defined by wall-clock lookback from "now", not by a tick
    count — that keeps uptime comparable across nodes even if one of them
    missed some ticks entirely.
    """
    cutoff_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    # SQLite compares ISO-8601 strings lexically, which is the right order
    # for our Zulu timestamps — cheaper than re-parsing.
    sql = """
    SELECT
        COUNT(*) AS total,
        SUM(success) AS ok
      FROM measurements
     WHERE node_url = ?
       AND timestamp >= datetime(?, ?)
    """
    delta = f"-{int(lookback_minutes)} minutes"
    with connect(db_path) as conn:
        row = conn.execute(sql, (node_url, cutoff_iso, delta)).fetchone()
    total = int(row["total"] or 0)
    ok = int(row["ok"] or 0)
    uptime_pct = (100.0 * ok / total) if total else 0.0
    return {
        "node_url": node_url,
        "lookback_minutes": lookback_minutes,
        "total": total,
        "ok": ok,
        "uptime_pct": round(uptime_pct, 2),
    }


def row_count(db_path: Path | str = DB_PATH) -> int:
    """Quick operational diagnostic — how many measurement rows do we have?"""
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM measurements").fetchone()
    return int(row["c"])


# =============================================================================
#  Phase 6 query helpers.
# =============================================================================
#
# Everything below powers the expanded dashboard (node detail, stats, regions,
# outages). These functions are read-only and idempotent; callers wrap them in
# `ttl_cache` at the API layer.


def get_measurements_range(
    node_url: str,
    lookback_minutes: int,
    db_path: Path | str = DB_PATH,
) -> list[dict]:
    """All measurements for one node within a wall-clock window, chronological.

    Covered by idx_measurements_node_ts — EXPLAIN QUERY PLAN confirms SEARCH
    USING INDEX for any lookback. Returns the rows sorted oldest-first so the
    outage detector and downsampler can iterate once.
    """
    cutoff_iso = _utcnow_iso()
    delta = f"-{int(lookback_minutes)} minutes"
    sql = """
    SELECT timestamp, node_url, success, latency_ms, block_height, error_message
      FROM measurements
     WHERE node_url = ?
       AND timestamp >= datetime(?, ?)
     ORDER BY timestamp ASC
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql, (node_url, cutoff_iso, delta)).fetchall()
    return [dict(r) for r in rows]


def get_all_measurements_range(
    lookback_minutes: int,
    db_path: Path | str = DB_PATH,
) -> list[dict]:
    """All measurements across every node within a window, chronological.

    Used by /api/v1/outages (global) and /stats/top(errors). Sorted by
    node_url first, then timestamp — the outage aggregator buckets by node
    and then walks each bucket in time order.
    """
    cutoff_iso = _utcnow_iso()
    delta = f"-{int(lookback_minutes)} minutes"
    sql = """
    SELECT timestamp, node_url, success, latency_ms, block_height, error_message
      FROM measurements
     WHERE timestamp >= datetime(?, ?)
     ORDER BY node_url ASC, timestamp ASC
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql, (cutoff_iso, delta)).fetchall()
    return [dict(r) for r in rows]


# ---------- Outage detection ------------------------------------------------

# The 2-minute threshold separating a transient hiccup from a real outage is
# fixed by the project's MEASUREMENT-METHODOLOGY concept doc. Exported so
# tests and the report generator can reuse it without drifting.
OUTAGE_SEVERITY_THRESHOLD_S = 120


def compute_outages(
    measurements: list[dict],
    *,
    now_iso: Optional[str] = None,
    severity_threshold_s: int = OUTAGE_SEVERITY_THRESHOLD_S,
) -> list[dict]:
    """Collapse a chronologically-ordered run of measurements into outages.

    An outage starts with the first `success=0` row and ends at the first
    subsequent `success=1` row. If the run never recovers within the
    supplied measurements, we treat the outage as ongoing and use `now_iso`
    (or the current UTC second) as its end — so a node that is currently
    down still shows a defined duration.

    Each entry carries:

    - start, end           : ISO timestamps (Z)
    - duration_s           : integer seconds
    - severity             : "short" (< threshold) or "real" (>= threshold)
    - error_sample         : first non-null error_message inside the run
    - ongoing              : True when the outage has no recovered row yet
    """
    outages: list[dict] = []
    run_start: Optional[str] = None
    run_error: Optional[str] = None

    for m in measurements:
        if not m["success"]:
            if run_start is None:
                run_start = m["timestamp"]
            if run_error is None and m.get("error_message"):
                run_error = m["error_message"]
            continue
        if run_start is not None:
            outages.append(_make_outage(run_start, m["timestamp"], run_error, severity_threshold_s, ongoing=False))
            run_start = None
            run_error = None

    if run_start is not None:
        end = now_iso or _utcnow_iso()
        outages.append(_make_outage(run_start, end, run_error, severity_threshold_s, ongoing=True))

    return outages


def _make_outage(start_iso: str, end_iso: str, error_sample: Optional[str], threshold_s: int, *, ongoing: bool) -> dict:
    start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    duration_s = max(0, int((end_dt - start_dt).total_seconds()))
    return {
        "start": start_iso,
        "end": end_iso,
        "duration_s": duration_s,
        "severity": "real" if duration_s >= threshold_s else "short",
        "error_sample": error_sample,
        "ongoing": ongoing,
    }


# ---------- Per-node aggregates used by /stats/top --------------------------


def get_per_node_aggregates(
    lookback_minutes: int,
    db_path: Path | str = DB_PATH,
) -> list[dict]:
    """Per-node avg/count summary within a window.

    One SQL pass produces avg_latency, success count, total count and
    error count per node. Anything needing higher-order stats (percentiles,
    outage lists) is done in Python on top of `get_measurements_range`.
    """
    cutoff_iso = _utcnow_iso()
    delta = f"-{int(lookback_minutes)} minutes"
    sql = """
    SELECT
        node_url,
        COUNT(*) AS total,
        SUM(success) AS ok,
        COUNT(*) - SUM(success) AS errors,
        AVG(CASE WHEN success=1 THEN latency_ms END) AS avg_latency_ms
      FROM measurements
     WHERE timestamp >= datetime(?, ?)
     GROUP BY node_url
    """
    with connect(db_path) as conn:
        rows = conn.execute(sql, (cutoff_iso, delta)).fetchall()
    out = []
    for r in rows:
        total = int(r["total"] or 0)
        ok = int(r["ok"] or 0)
        out.append({
            "node_url": r["node_url"],
            "total": total,
            "ok": ok,
            "errors": int(r["errors"] or 0),
            "avg_latency_ms": round(r["avg_latency_ms"], 1) if r["avg_latency_ms"] is not None else None,
            "uptime_pct": round(100.0 * ok / total, 2) if total else 0.0,
        })
    return out
