"""Aggregation tests — pure functions, no DB, no clock.

These exercise the arithmetic that the daily report hangs off: per-node
rollup, global ranking, longest-outage detection, and week-over-week
deltas. The input is always synthetic lists of row-dicts shaped like what
`reporter.query.fetch_measurements_in_window` returns, so a future schema
change in the measurements table only breaks `query.py`, not these tests.
"""

from __future__ import annotations

import pytest

from reporter import aggregation


def _row(ts: str, ok: bool = True, latency: int | None = 200,
         height: int | None = 1000, err: str | None = None) -> dict:
    return {
        "timestamp": ts,
        "success": 1 if ok else 0,
        "latency_ms": latency,
        "block_height": height,
        "error_message": err,
    }


def test_aggregate_node_uptime_and_latency_bands():
    # 8 ok, 2 fail → 80 % uptime. Latency avg is mean of OK ticks only.
    rows = []
    for i, lat in enumerate([100, 120, 140, 160, 180, 200, 300, 500]):
        rows.append(_row(f"2026-04-24T10:{i:02d}:00Z", ok=True, latency=lat))
    rows.append(_row("2026-04-24T10:08:00Z", ok=False, latency=None,
                     height=None, err="timeout"))
    rows.append(_row("2026-04-24T10:09:00Z", ok=False, latency=None,
                     height=None, err="HTTP 502"))

    stats = aggregation.aggregate_node(rows, url="https://x.example", region="eu")
    assert stats.total == 10
    assert stats.ok == 8
    assert stats.uptime_pct == 80.0
    assert stats.errors == 2
    assert stats.latency.min_ms == 100
    assert stats.latency.max_ms == 500
    # Mean over [100,120,140,160,180,200,300,500] = 212.5 → 212 after int().
    assert stats.latency.avg_ms == 212
    # Error classes bucketed by monitor.py's free-form strings.
    assert stats.error_classes == {"timeout": 1, "http_5xx": 1}


def test_aggregate_node_all_ok_has_no_error_classes():
    rows = [_row(f"2026-04-24T10:{i:02d}:00Z") for i in range(5)]
    stats = aggregation.aggregate_node(rows, url="https://x.example", region=None)
    assert stats.errors == 0
    assert stats.error_classes == {}
    assert stats.latency.avg_ms == 200


def test_aggregate_node_empty_returns_zero_uptime_and_null_latency():
    stats = aggregation.aggregate_node([], url="https://x.example", region=None)
    assert stats.total == 0
    assert stats.ok == 0
    assert stats.uptime_pct == 0.0
    assert stats.latency.avg_ms is None
    assert stats.latency.p95_ms is None


def test_p95_handles_small_samples():
    # Nearest-rank on a single-element list returns that element.
    s = aggregation.aggregate_node(
        [_row("2026-04-24T10:00:00Z", latency=123)],
        url="a", region=None,
    )
    assert s.latency.p95_ms == 123


def test_longest_outage_streak_spans_multiple_ticks():
    rows_by_node = {
        "https://a.example": [
            _row("2026-04-24T10:00:00Z", ok=True),
            _row("2026-04-24T10:01:00Z", ok=False, err="timeout"),
            _row("2026-04-24T10:02:00Z", ok=False, err="timeout"),
            _row("2026-04-24T10:03:00Z", ok=False, err="timeout"),
            _row("2026-04-24T10:04:00Z", ok=True),
        ],
        "https://b.example": [
            _row("2026-04-24T10:00:00Z", ok=True),
            _row("2026-04-24T10:01:00Z", ok=False, err="timeout"),
            _row("2026-04-24T10:02:00Z", ok=True),
        ],
    }
    per_node = {
        url: aggregation.aggregate_node(rs, url=url, region=None)
        for url, rs in rows_by_node.items()
    }
    gs = aggregation.aggregate_global(per_node, rows_by_node)
    assert gs.longest_outage_node == "https://a.example"
    assert gs.longest_outage_ticks == 3


def test_global_ranking_picks_best_and_worst_by_uptime():
    rows_by_node = {
        "https://best.example": [_row(f"2026-04-24T10:{i:02d}:00Z") for i in range(10)],
        "https://worst.example": [
            _row(f"2026-04-24T10:{i:02d}:00Z", ok=(i < 4), latency=200 if i < 4 else None,
                 height=1000 if i < 4 else None, err=None if i < 4 else "timeout")
            for i in range(10)
        ],
        "https://mid.example": [
            _row(f"2026-04-24T10:{i:02d}:00Z", ok=(i < 8), latency=200 if i < 8 else None,
                 height=1000 if i < 8 else None, err=None if i < 8 else "timeout")
            for i in range(10)
        ],
    }
    per_node = {
        url: aggregation.aggregate_node(rs, url=url, region=None)
        for url, rs in rows_by_node.items()
    }
    gs = aggregation.aggregate_global(per_node, rows_by_node)
    assert gs.best_node == "https://best.example"
    assert gs.worst_node == "https://worst.example"
    assert gs.total_measurements == 30
    assert gs.total_ok == 10 + 4 + 8


def test_week_comparison_returns_none_without_previous_data():
    cur = {"a": [_row("2026-04-24T10:00:00Z")]}
    cmp = aggregation.compare_weeks(cur, {})
    assert cmp is None


def test_week_comparison_computes_signed_delta():
    # Current week 95 % (9500 ok of 10 000), previous 80 % (8000 ok of 10 000).
    # Using min_rows_per_node=1000 with 2000 rows / node → comparison emits.
    def _make(uptime_pct: float) -> dict[str, list[dict]]:
        rows_by_node: dict[str, list[dict]] = {}
        for url, n_rows in [("a", 5000), ("b", 5000)]:
            n_ok = int(n_rows * uptime_pct / 100)
            rows_by_node[url] = (
                [_row(f"2026-04-24T00:{i:02d}:00Z", ok=True) for i in range(n_ok)]
                + [_row(f"2026-04-24T00:{i:02d}:00Z", ok=False, err="timeout")
                   for i in range(n_rows - n_ok)]
            )
        return rows_by_node

    cmp = aggregation.compare_weeks(_make(95.0), _make(80.0), min_rows_per_node=1000)
    assert cmp is not None
    assert cmp.current_uptime_pct == 95.0
    assert cmp.previous_uptime_pct == 80.0
    assert cmp.delta_pp == 15.0
    # Both per-node entries populated.
    assert set(cmp.per_node_delta_pp) == {"a", "b"}
    assert cmp.per_node_delta_pp["a"] == 15.0


def test_custom_json_payload_shape_is_stable():
    rows_by_node = {
        "https://a.example": [
            _row("2026-04-24T10:00:00Z", latency=200, height=100),
            _row("2026-04-24T10:01:00Z", ok=False, latency=None, height=None, err="timeout"),
        ],
    }
    per_node = {
        url: aggregation.aggregate_node(rs, url=url, region="eu")
        for url, rs in rows_by_node.items()
    }
    gs = aggregation.aggregate_global(per_node, rows_by_node)
    payload = aggregation.to_custom_json_payload(
        day="2026-04-24",
        window_start="2026-04-24T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        source_location="test",
        methodology_version="mv1",
        per_node=per_node,
        global_stats=gs,
    )
    assert payload["version"] == "mv1"
    assert payload["day"] == "2026-04-24"
    assert payload["source_location"] == "test"
    assert payload["window"] == {"start": "2026-04-24T00:00:00Z",
                                 "end": "2026-04-25T00:00:00Z"}
    assert payload["summary"]["uptime_pct"] == 50.0
    assert payload["summary"]["total_measurements"] == 2
    assert len(payload["nodes"]) == 1
    node = payload["nodes"][0]
    assert node["url"] == "https://a.example"
    assert node["region"] == "eu"
    assert set(node["latency_ms"]) == {"avg", "min", "max", "p50", "p95", "p99"}
    assert node["error_classes"] == {"timeout": 1}
