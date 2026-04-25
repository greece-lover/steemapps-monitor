"""Etappe 12a — extended aggregations for the daily report.

Pure-function tests, same shape as test_aggregation.py: synthetic row
dicts in, dataclass out, no DB or clock dependency.
"""

from __future__ import annotations

import pytest

from reporter import aggregation
from reporter.aggregation import (
    CrossRegionResult,
    ErrorBreakdown,
    HourPattern,
    LatencyDistribution,
    NodeStats,
    PerformanceGap,
    ReliabilityRanking,
)


# ---------------------------------------------------------------------------
#  Helper builders
# ---------------------------------------------------------------------------

def _row(ts: str, ok: bool = True, latency: int | None = 200,
         err: str | None = None, source: str | None = None) -> dict:
    return {
        "timestamp": ts,
        "success": 1 if ok else 0,
        "latency_ms": latency,
        "block_height": 1000 if ok else None,
        "error_message": err,
        "source_location": source,
    }


def _ns(url: str, *, avg: int | None, uptime: float = 100.0,
        errors: int = 0, error_classes: dict | None = None) -> NodeStats:
    """Synthesise a NodeStats without going through aggregate_node."""
    return NodeStats(
        url=url, region=None, total=100,
        ok=int(100 * uptime / 100), uptime_pct=uptime,
        errors=errors,
        latency=aggregation.LatencyStats(
            avg_ms=avg, min_ms=avg, max_ms=avg,
            p50_ms=avg, p95_ms=avg, p99_ms=avg,
        ),
        error_classes=error_classes or {},
    )


# ===========================================================================
#  Pre-existing schema: LatencyStats now exposes p50, p95, p99
# ===========================================================================

def test_latency_stats_has_p50_and_p99():
    rows = [_row(f"2026-04-25T10:{i:02d}:00Z", latency=l)
            for i, l in enumerate([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000])]
    s = aggregation.aggregate_node(rows, url="x", region=None)
    # Nearest-rank: p50 of 10 evenly-spaced values lands on index round(0.5*9)=4 → 500.
    assert s.latency.p50_ms == 500
    # p95 → index round(0.95*9)=9 → 1000.
    assert s.latency.p95_ms == 1000
    # p99 → same index for this small sample.
    assert s.latency.p99_ms == 1000


# ===========================================================================
#  A) compute_latency_distribution
# ===========================================================================

def test_latency_distribution_cumulative_buckets():
    # 4 fast (<200), 3 mid (<500), 2 slow (<1000), 1 super-slow (>1000)
    latencies = [50, 100, 150, 199, 250, 400, 499, 750, 999, 1500]
    rows = [_row(f"2026-04-25T10:{i:02d}:00Z", latency=l) for i, l in enumerate(latencies)]
    d = aggregation.compute_latency_distribution(rows)
    assert d.sample_size == 10
    assert d.pct_under_200ms == 40.0     # 4/10
    assert d.pct_under_500ms == 70.0     # 7/10
    assert d.pct_under_1000ms == 90.0    # 9/10
    assert d.pct_above_1000ms == 10.0    # 1/10


def test_latency_distribution_empty_returns_zeros():
    d = aggregation.compute_latency_distribution([])
    assert d == LatencyDistribution(0, 0.0, 0.0, 0.0, 0.0)


def test_latency_distribution_drops_failed_ticks():
    """A failed tick has no measurable latency — must not be counted."""
    rows = [
        _row("2026-04-25T10:00:00Z", latency=100),
        _row("2026-04-25T10:01:00Z", ok=False, latency=None, err="timeout"),
    ]
    d = aggregation.compute_latency_distribution(rows)
    assert d.sample_size == 1
    assert d.pct_under_200ms == 100.0


# ===========================================================================
#  B) compute_hour_pattern
# ===========================================================================

def test_hour_pattern_picks_best_and_worst_populated_hours():
    # Hour 03 = 100 ms, hour 18 = 500 ms, others empty.
    rows = []
    for i in range(5):
        rows.append(_row(f"2026-04-25T03:{i:02d}:00Z", latency=100))
    for i in range(5):
        rows.append(_row(f"2026-04-25T18:{i:02d}:00Z", latency=500))
    p = aggregation.compute_hour_pattern(rows)
    assert len(p.buckets) == 24
    assert p.best.hour_utc == 3
    assert p.best.avg_latency_ms == 100
    assert p.worst.hour_utc == 18
    assert p.worst.avg_latency_ms == 500
    # Empty hours render as None — the chart must show the gap.
    assert p.buckets[0].avg_latency_ms is None
    assert p.buckets[12].sample_size == 0


def test_hour_pattern_empty_returns_24_empty_buckets():
    p = aggregation.compute_hour_pattern([])
    assert len(p.buckets) == 24
    assert p.best is None
    assert p.worst is None
    assert all(b.avg_latency_ms is None for b in p.buckets)


def test_hour_pattern_ignores_failed_ticks():
    rows = [
        _row("2026-04-25T03:00:00Z", latency=100),
        _row("2026-04-25T03:01:00Z", ok=False, latency=None, err="timeout"),
    ]
    p = aggregation.compute_hour_pattern(rows)
    assert p.best.sample_size == 1


# ===========================================================================
#  C) compute_error_breakdown
# ===========================================================================

def test_error_breakdown_top_three_with_percent():
    per_node = {
        "a": _ns("a", avg=100, errors=10,
                 error_classes={"connect_error": 6, "timeout": 3, "http_5xx": 1}),
        "b": _ns("b", avg=100, errors=4,
                 error_classes={"timeout": 2, "rpc_error": 2}),
    }
    eb = aggregation.compute_error_breakdown(per_node)
    assert eb.total_errors == 14
    # top-3 by count, sorted desc.
    assert [t.bucket for t in eb.top] == ["connect_error", "timeout", "rpc_error"]
    assert eb.top[0].count == 6
    assert eb.top[0].pct == round(100 * 6 / 14, 1)
    # top-3 only — http_5xx must be excluded.
    assert all(t.bucket != "http_5xx" for t in eb.top)


def test_error_breakdown_empty_when_no_errors():
    per_node = {"a": _ns("a", avg=100)}
    eb = aggregation.compute_error_breakdown(per_node)
    assert eb.total_errors == 0
    assert eb.top == []


# ===========================================================================
#  D) compute_performance_gap
# ===========================================================================

def test_performance_gap_factor_today_only():
    today = {"a": _ns("a", avg=100), "b": _ns("b", avg=300), "c": _ns("c", avg=200)}
    g = aggregation.compute_performance_gap(today, prev_per_node=None)
    assert g.today_fastest_ms == 100
    assert g.today_slowest_ms == 300
    assert g.today_factor == 3.0
    assert g.prev_factor is None
    assert g.trend == "no_history"


def test_performance_gap_widening_trend():
    today = {"a": _ns("a", avg=100), "b": _ns("b", avg=400)}      # factor 4.0
    prev = {"a": _ns("a", avg=100), "b": _ns("b", avg=200)}        # factor 2.0
    g = aggregation.compute_performance_gap(today, prev_per_node=prev)
    assert g.today_factor == 4.0
    assert g.prev_factor == 2.0
    assert g.trend == "widening"


def test_performance_gap_narrowing_trend():
    today = {"a": _ns("a", avg=100), "b": _ns("b", avg=120)}      # factor 1.2
    prev = {"a": _ns("a", avg=100), "b": _ns("b", avg=400)}        # factor 4.0
    g = aggregation.compute_performance_gap(today, prev_per_node=prev)
    assert g.trend == "narrowing"


def test_performance_gap_stable_within_threshold():
    today = {"a": _ns("a", avg=100), "b": _ns("b", avg=210)}      # factor 2.1
    prev = {"a": _ns("a", avg=100), "b": _ns("b", avg=200)}        # factor 2.0
    # Change is 5%, below default 10% threshold.
    g = aggregation.compute_performance_gap(today, prev_per_node=prev)
    assert g.trend == "stable"


def test_performance_gap_no_measurable_nodes():
    today = {"a": _ns("a", avg=None)}
    g = aggregation.compute_performance_gap(today, prev_per_node=None)
    assert g.today_factor is None
    assert g.trend == "no_history"


# ===========================================================================
#  E) compute_cross_region_variance
# ===========================================================================

def test_cross_region_variance_picks_nodes_seen_from_multiple_regions():
    # node A seen from de (200ms) and asia (450ms) → factor 2.25
    # node B seen only from de → excluded
    rows_by_node = {
        "https://a.example": [
            _row("t1", latency=180, source="Welako VM (DE)"),
            _row("t2", latency=220, source="Welako VM (DE)"),
            _row("t3", latency=400, source="Bob (Asia)"),
            _row("t4", latency=500, source="Bob (Asia)"),
        ],
        "https://b.example": [
            _row("t1", latency=200, source="Welako VM (DE)"),
            _row("t2", latency=210, source="Welako VM (DE)"),
        ],
    }
    src_to_region = {"Welako VM (DE)": "eu-central", "Bob (Asia)": "asia"}
    res = aggregation.compute_cross_region_variance(rows_by_node, src_to_region)
    assert len(res.entries) == 1
    e = res.entries[0]
    assert e.node_url == "https://a.example"
    assert e.by_region == {"eu-central": 200, "asia": 450}
    assert e.variance_factor == 2.25


def test_cross_region_variance_empty_when_only_one_region():
    rows_by_node = {
        "https://a.example": [
            _row("t1", latency=200, source="Welako VM (DE)"),
        ],
    }
    res = aggregation.compute_cross_region_variance(
        rows_by_node, {"Welako VM (DE)": "eu-central"},
    )
    assert res.entries == []


def test_cross_region_variance_ignores_unmapped_sources():
    """A row written with a source_location not in the map (e.g. legacy
    'demo' rows from --seed-synthetic) must not crash and not be counted."""
    rows_by_node = {
        "https://a.example": [
            _row("t1", latency=200, source="demo"),
            _row("t2", latency=400, source="Bob (Asia)"),
        ],
    }
    res = aggregation.compute_cross_region_variance(
        rows_by_node, {"Bob (Asia)": "asia"},
    )
    # Only one usable region → entry skipped.
    assert res.entries == []


def test_cross_region_variance_sorted_by_variance_desc():
    rows_by_node = {
        "https://wide.example": [
            _row("t1", latency=100, source="src-de"),
            _row("t2", latency=400, source="src-asia"),
        ],
        "https://narrow.example": [
            _row("t1", latency=100, source="src-de"),
            _row("t2", latency=120, source="src-asia"),
        ],
    }
    res = aggregation.compute_cross_region_variance(
        rows_by_node, {"src-de": "eu", "src-asia": "asia"},
    )
    assert [e.node_url for e in res.entries] == [
        "https://wide.example", "https://narrow.example",
    ]


# ===========================================================================
#  F) compute_reliability_ranking
# ===========================================================================

def test_reliability_ranking_top_bottom_and_streak():
    # Helper: build a "day" with the given uptime per node.
    def _day(per_node_uptime: dict[str, float], n_rows: int = 200) -> dict:
        out = {}
        for url, pct in per_node_uptime.items():
            ok_count = int(n_rows * pct / 100)
            rows = (
                [_row(f"2026-04-{i:02d}T10:00:00Z", ok=True) for i in range(ok_count)]
                + [_row(f"2026-04-{i:02d}T10:01:00Z", ok=False, latency=None, err="timeout")
                   for i in range(n_rows - ok_count)]
            )
            out[url] = rows
        return out

    # 7 days. Node a is perfect every day, node b is mostly good, node c
    # has trouble. Streak winner should be node a with 7 days.
    days = [
        _day({"a": 100, "b": 95, "c": 80}),
        _day({"a": 100, "b": 95, "c": 80}),
        _day({"a": 100, "b": 95, "c": 80}),
        _day({"a": 100, "b": 95, "c": 80}),
        _day({"a": 100, "b": 95, "c": 80}),
        _day({"a": 100, "b": 95, "c": 80}),
        _day({"a": 100, "b": 95, "c": 80}),
    ]
    r = aggregation.compute_reliability_ranking(days)
    assert r.days_actual == 7
    assert r.top[0].node_url == "a"
    assert r.top[0].uptime_pct == 100.0
    assert r.bottom[0].node_url == "c"
    assert r.longest_streak_node == "a"
    assert r.longest_streak_days == 7


def test_reliability_ranking_streak_breaks_on_failure():
    """A single failing tick on a day kills that day's streak contribution."""
    def _clean(url: str, n: int) -> list[dict]:
        return [_row(f"2026-04-XX-{url}-{i}", ok=True) for i in range(n)]
    def _dirty(url: str, n: int) -> list[dict]:
        rows = _clean(url, n - 1)
        rows.append(_row(f"2026-04-XX-{url}-fail", ok=False, latency=None, err="timeout"))
        return rows

    days = [
        {"a": _clean("a", 200), "b": _clean("b", 200)},
        {"a": _dirty("a", 200), "b": _clean("b", 200)},   # a's streak breaks
        {"a": _clean("a", 200), "b": _clean("b", 200)},
        {"a": _clean("a", 200), "b": _clean("b", 200)},
    ]
    r = aggregation.compute_reliability_ranking(days)
    # Node b has a 4-day clean streak; node a has at most 2 (the trailing run).
    assert r.longest_streak_node == "b"
    assert r.longest_streak_days == 4


def test_reliability_ranking_empty_history_returns_empty_ranking():
    r = aggregation.compute_reliability_ranking([])
    assert r.days_actual == 0
    assert r.top == []
    assert r.bottom == []
    assert r.longest_streak_node is None


def test_reliability_ranking_excludes_low_coverage_nodes():
    """Nodes with fewer than min_rows_per_day rows in total are dropped."""
    days = [
        {"a": [_row(f"t{i}", ok=True) for i in range(200)],
         "b": [_row("t0", ok=True)]},   # only 1 row total — below threshold
    ]
    r = aggregation.compute_reliability_ranking(days, min_rows_per_day=100)
    assert {e.node_url for e in r.top} == {"a"}
    assert all(e.node_url != "b" for e in r.top + r.bottom)


# ===========================================================================
#  to_custom_json_payload — error_breakdown additive field
# ===========================================================================

def test_custom_json_payload_includes_error_breakdown_when_supplied():
    per_node = {
        "https://a.example": _ns("https://a.example", avg=200, errors=5,
                                 error_classes={"timeout": 5}),
    }
    rows_by_node = {"https://a.example": []}  # not used inside aggregate_global path
    gs = aggregation.aggregate_global(per_node, rows_by_node)
    eb = aggregation.compute_error_breakdown(per_node)
    payload = aggregation.to_custom_json_payload(
        day="2026-04-25",
        window_start="2026-04-25T00:00:00Z",
        window_end="2026-04-26T00:00:00Z",
        source_location="test",
        methodology_version="mv1",
        per_node=per_node, global_stats=gs,
        error_breakdown=eb,
    )
    assert "error_breakdown" in payload["summary"]
    assert payload["summary"]["error_breakdown"]["total_errors"] == 5
    assert payload["summary"]["error_breakdown"]["top"][0]["bucket"] == "timeout"


def test_custom_json_payload_omits_error_breakdown_field_when_not_supplied():
    """Backwards compatibility: a caller that does not pass error_breakdown
    must produce a payload without the new key (not with `null`)."""
    per_node = {"https://a.example": _ns("https://a.example", avg=200)}
    gs = aggregation.aggregate_global(per_node, {"https://a.example": []})
    payload = aggregation.to_custom_json_payload(
        day="2026-04-25",
        window_start="2026-04-25T00:00:00Z",
        window_end="2026-04-26T00:00:00Z",
        source_location="test",
        methodology_version="mv1",
        per_node=per_node, global_stats=gs,
    )
    assert "error_breakdown" not in payload["summary"]
