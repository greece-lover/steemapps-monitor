"""Benchmark the Phase-6 query layer against a 1-million-row SQLite.

Runs once manually — *not* part of CI. Drops a fresh SQLite file into
a temp directory, fills it with 1 M synthetic measurements (10 nodes ×
100 000 ticks, one tick per minute), then times every Phase-6 query
helper. Output is formatted for direct pasting into docs/PERFORMANCE.md.

Usage:
    .venv/Scripts/python scripts/bench_load.py            # default: 1 M rows
    .venv/Scripts/python scripts/bench_load.py --rows 100000   # quicker
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow running from anywhere — resolve the project root relative to this file.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import config
import database


def isoZ(dt: datetime) -> str:
    """Produce the exact `YYYY-MM-DDTHH:MM:SSZ` shape the monitor writes."""
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def populate(db_path: Path, rows: int, nodes: int) -> None:
    """Bulk-insert `rows` synthetic measurements distributed across `nodes`.

    Uses executemany + a single transaction. Anything smaller runs into
    sqlite3's per-statement fsync overhead and turns 1 M inserts into a
    multi-minute wait."""
    ticks_per_node = rows // nodes
    urls = [f"https://bench-node-{i:02d}.example" for i in range(nodes)]
    now = datetime.now(timezone.utc)

    print(f"Populating {rows:,} rows ({ticks_per_node:,} per node × {nodes} nodes)…", flush=True)
    t0 = time.time()
    with database.connect(db_path) as conn:
        # sync_nodes expects the nodes.json shape.
        database.sync_nodes([{"url": u, "region": "bench"} for u in urls], db_path=db_path)
        conn.execute("BEGIN")
        batch: list[tuple] = []
        BATCH_SIZE = 5000
        block_height = 100_000_000
        for tick in range(ticks_per_node):
            ts = isoZ(now - timedelta(seconds=tick * 60))
            block_height += 1
            for node in urls:
                # 95 % of ticks succeed, 5 % fail — realistic fleet average.
                ok = 0 if random.random() < 0.05 else 1
                latency = random.randint(40, 800) if ok else None
                err = None if ok else random.choice(["timeout", "HTTP 502", "conn reset"])
                batch.append((ts, node, ok, latency, block_height if ok else None, err, "bench"))
            if len(batch) >= BATCH_SIZE:
                conn.executemany(
                    "INSERT INTO measurements "
                    "(timestamp, node_url, success, latency_ms, block_height, error_message, source_location) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                batch.clear()
        if batch:
            conn.executemany(
                "INSERT INTO measurements "
                "(timestamp, node_url, success, latency_ms, block_height, error_message, source_location) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
        conn.execute("COMMIT")
    elapsed = time.time() - t0
    print(f"Inserted in {elapsed:.1f} s ({int(rows / elapsed):,} rows/s)")


def bench(db_path: Path, node_url: str) -> list[tuple]:
    """Time each query helper and return a list of (label, ms, count)."""
    results: list[tuple] = []

    def run(label: str, fn):
        t0 = time.time()
        out = fn()
        took = (time.time() - t0) * 1000
        count = len(out) if hasattr(out, "__len__") else None
        results.append((label, took, count))

    run("get_latest_per_node",                       lambda: database.get_latest_per_node(db_path=db_path))
    run("get_recent_measurements(100)",              lambda: database.get_recent_measurements(node_url, 100, db_path=db_path))
    run("get_per_node_aggregates(24h)",              lambda: database.get_per_node_aggregates(24 * 60, db_path=db_path))
    run("get_per_node_aggregates(7d)",               lambda: database.get_per_node_aggregates(7 * 24 * 60, db_path=db_path))
    run("get_per_node_aggregates(30d)",              lambda: database.get_per_node_aggregates(30 * 24 * 60, db_path=db_path))
    run("get_per_node_aggregates_between(yday)",     lambda: database.get_per_node_aggregates_between(48 * 60, 24 * 60, db_path=db_path))
    run("get_measurements_range(24h, one-node)",     lambda: database.get_measurements_range(node_url, 24 * 60, db_path=db_path))
    run("get_measurements_range(7d, one-node)",      lambda: database.get_measurements_range(node_url, 7 * 24 * 60, db_path=db_path))
    run("get_all_measurements_range(24h)",           lambda: database.get_all_measurements_range(24 * 60, db_path=db_path))
    run("get_chain_availability(24h,600s)",          lambda: database.get_chain_availability(24 * 60, 600, db_path=db_path))
    run("get_chain_availability(7d,3600s)",          lambda: database.get_chain_availability(7 * 24 * 60, 3600, db_path=db_path))
    run("get_uptime_stats(7d, one-node)",            lambda: database.get_uptime_stats(node_url, 7 * 24 * 60, db_path=db_path))
    run("get_uptime_daily(30d, one-node)",           lambda: database.get_uptime_daily(node_url, 30, db_path=db_path))
    run("row_count (total)",                         lambda: database.row_count(db_path=db_path))

    return results


def format_markdown(results: list[tuple], total_rows: int) -> str:
    """Render the benchmark output as a Markdown table ready to paste."""
    lines = [
        f"# Performance snapshot — {total_rows:,} rows (SQLite, Phase 6 helpers)",
        "",
        "| Query | Time (ms) | Rows |",
        "|---|---:|---:|",
    ]
    for label, ms, count in results:
        shown = "—" if count is None else f"{count:,}"
        lines.append(f"| `{label}` | {ms:,.1f} | {shown} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=1_000_000, help="total rows to insert")
    ap.add_argument("--nodes", type=int, default=10, help="number of nodes")
    ap.add_argument("--keep", action="store_true", help="keep the temp SQLite after run")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="bench-"))
    db_path = tmp / "bench.sqlite"
    database.initialise(db_path)

    populate(db_path, args.rows, args.nodes)

    # We need a node URL to pass into per-node helpers; the bulk-insert
    # used bench-node-00 … bench-node-09, so pick the first.
    node = f"https://bench-node-00.example"

    print("\nRunning query benchmarks…", flush=True)
    results = bench(db_path, node)

    markdown = format_markdown(results, args.rows)
    print("\n" + markdown)

    if args.keep:
        print(f"Kept DB at: {db_path}")


if __name__ == "__main__":
    main()
