"""Pure aggregation functions over a list of measurement rows.

Every function here is deterministic and has no I/O — the caller is
expected to load rows via `reporter.query` and hand them over. That keeps
the aggregation trivially unit-testable with synthetic inputs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional


@dataclass(frozen=True)
class LatencyStats:
    avg_ms: Optional[int]
    min_ms: Optional[int]
    max_ms: Optional[int]
    p95_ms: Optional[int]


@dataclass(frozen=True)
class NodeStats:
    url: str
    region: Optional[str]
    total: int
    ok: int
    uptime_pct: float
    errors: int
    latency: LatencyStats
    # A compact view of which error classes showed up during the window.
    # Keys are the free-text error_message strings the monitor writes
    # (`timeout`, `HTTP 502`, `rpc_error: …`, etc.); values are counts.
    error_classes: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class GlobalStats:
    total_measurements: int
    total_ok: int
    uptime_pct: float
    best_node: Optional[str]
    worst_node: Optional[str]
    # The node with the longest single run of consecutive failures within
    # the window. None if the window had zero failures across all nodes.
    longest_outage_node: Optional[str]
    longest_outage_ticks: int


@dataclass(frozen=True)
class WeekComparison:
    """Deltas of global uptime and per-node uptime between two 7-day windows.

    `None` for any field means we did not have enough data for that node in
    one of the two windows and skipped the comparison.
    """
    current_uptime_pct: float
    previous_uptime_pct: float
    delta_pp: float  # percentage points, current minus previous
    per_node_delta_pp: dict[str, float] = field(default_factory=dict)


def _p95(values: list[int]) -> Optional[int]:
    """Simple nearest-rank p95 — good enough for a few thousand samples.

    Uses a sorted-list lookup rather than a heavy stats library; the report
    runs once a day over at most ~1440 samples per node, not a streaming
    workload.
    """
    if not values:
        return None
    s = sorted(values)
    # Nearest-rank p95: 0-based index into a 0-indexed sorted list.
    idx = max(0, min(len(s) - 1, int(round(0.95 * (len(s) - 1)))))
    return int(s[idx])


def aggregate_node(rows: list[dict], url: str, region: Optional[str]) -> NodeStats:
    """Compute per-node stats for one 24-hour window.

    `latency_ms` is averaged over successful ticks only — a timeout that
    ran for 8 000 ms would otherwise poison the mean.
    """
    total = len(rows)
    ok = sum(1 for r in rows if r["success"])
    errors = total - ok
    uptime = (100.0 * ok / total) if total else 0.0
    latencies = [
        int(r["latency_ms"])
        for r in rows
        if r["success"] and r["latency_ms"] is not None
    ]
    lat = LatencyStats(
        avg_ms=int(sum(latencies) / len(latencies)) if latencies else None,
        min_ms=min(latencies) if latencies else None,
        max_ms=max(latencies) if latencies else None,
        p95_ms=_p95(latencies),
    )
    classes: dict[str, int] = {}
    for r in rows:
        if not r["success"]:
            # Normalise the error_message into short buckets so a thousand
            # slightly-different "connect_error: [Errno 111] …" lines don't
            # each become their own key.
            msg = (r["error_message"] or "unknown")
            bucket = _error_bucket(msg)
            classes[bucket] = classes.get(bucket, 0) + 1
    return NodeStats(
        url=url,
        region=region,
        total=total,
        ok=ok,
        uptime_pct=round(uptime, 2),
        errors=errors,
        latency=lat,
        error_classes=classes,
    )


def _error_bucket(msg: str) -> str:
    """Collapse monitor.py's free-form error strings into short labels."""
    m = msg.lower()
    if m.startswith("timeout"):
        return "timeout"
    if m.startswith("connect_error"):
        return "connect_error"
    if m.startswith("http "):
        # e.g. 'HTTP 502' → 'http_5xx'.
        parts = msg.split()
        if len(parts) >= 2 and parts[1].isdigit():
            n = int(parts[1])
            if 500 <= n < 600:
                return "http_5xx"
            if 400 <= n < 500:
                return "http_4xx"
        return "http_other"
    if m.startswith("rpc_error"):
        return "rpc_error"
    if m.startswith("body_invalid"):
        return "body_invalid"
    if m.startswith("body_stale"):
        return "body_stale"
    return "other"


def _longest_failure_streak(rows: list[dict]) -> int:
    """Length of the longest consecutive run of failed ticks in the list."""
    longest = 0
    current = 0
    for r in rows:
        if not r["success"]:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def aggregate_global(per_node: dict[str, NodeStats], rows_by_node: dict[str, list[dict]]) -> GlobalStats:
    """Roll up per-node stats and find the worst single outage."""
    if not per_node:
        return GlobalStats(
            total_measurements=0, total_ok=0, uptime_pct=0.0,
            best_node=None, worst_node=None,
            longest_outage_node=None, longest_outage_ticks=0,
        )
    total = sum(s.total for s in per_node.values())
    ok = sum(s.ok for s in per_node.values())
    # Rank by uptime, then (as tiebreaker) lower avg latency is better.
    def _rank_key(s: NodeStats) -> tuple[float, int]:
        return (s.uptime_pct, -(s.latency.avg_ms if s.latency.avg_ms is not None else 10**9))
    ranked = sorted(per_node.values(), key=_rank_key)
    worst = ranked[0].url if ranked else None
    best = ranked[-1].url if ranked else None

    longest_node: Optional[str] = None
    longest_ticks = 0
    for url, node_rows in rows_by_node.items():
        streak = _longest_failure_streak(node_rows)
        if streak > longest_ticks:
            longest_ticks = streak
            longest_node = url

    return GlobalStats(
        total_measurements=total,
        total_ok=ok,
        uptime_pct=round(100.0 * ok / total, 2) if total else 0.0,
        best_node=best,
        worst_node=worst,
        longest_outage_node=longest_node,
        longest_outage_ticks=longest_ticks,
    )


def compare_weeks(current_rows_by_node: dict[str, list[dict]],
                  previous_rows_by_node: dict[str, list[dict]],
                  min_rows_per_node: int = 1000) -> Optional[WeekComparison]:
    """Week-over-week delta. Returns None if the previous week has no data.

    `min_rows_per_node` guards against running the comparison on a partial
    historical window — e.g. if the monitor was only turned on halfway
    through the previous week, the "delta" would be noise. With a 60 s poll
    interval, 1 000 rows ≈ 16.7 hours, so a node with less than that in one
    of the windows is excluded from the per-node table.
    """
    if not previous_rows_by_node:
        return None

    def _uptime(rows: list[dict]) -> Optional[float]:
        if not rows:
            return None
        ok = sum(1 for r in rows if r["success"])
        return 100.0 * ok / len(rows)

    cur_total = sum(len(v) for v in current_rows_by_node.values())
    prev_total = sum(len(v) for v in previous_rows_by_node.values())
    if cur_total == 0 or prev_total == 0:
        return None
    cur_ok = sum(1 for rs in current_rows_by_node.values() for r in rs if r["success"])
    prev_ok = sum(1 for rs in previous_rows_by_node.values() for r in rs if r["success"])
    cur_pct = 100.0 * cur_ok / cur_total
    prev_pct = 100.0 * prev_ok / prev_total

    per_node: dict[str, float] = {}
    for url in set(current_rows_by_node) | set(previous_rows_by_node):
        cur = current_rows_by_node.get(url, [])
        prev = previous_rows_by_node.get(url, [])
        if len(cur) < min_rows_per_node or len(prev) < min_rows_per_node:
            continue
        cu = _uptime(cur)
        pu = _uptime(prev)
        if cu is None or pu is None:
            continue
        per_node[url] = round(cu - pu, 2)

    return WeekComparison(
        current_uptime_pct=round(cur_pct, 2),
        previous_uptime_pct=round(prev_pct, 2),
        delta_pp=round(cur_pct - prev_pct, 2),
        per_node_delta_pp=per_node,
    )


def to_custom_json_payload(
    day: str,
    window_start: str,
    window_end: str,
    source_location: str,
    methodology_version: str,
    per_node: dict[str, NodeStats],
    global_stats: GlobalStats,
) -> dict:
    """Serialise the aggregates into the stable on-chain schema.

    Anyone consuming the `custom_json` operation downstream (Welako,
    third-party dashboards) can rely on these keys. A breaking change to
    the shape warrants a new operation id, not a silent format shift.
    """
    return {
        "version": methodology_version,
        "day": day,
        "window": {"start": window_start, "end": window_end},
        "source_location": source_location,
        "summary": {
            "total_measurements": global_stats.total_measurements,
            "total_ok": global_stats.total_ok,
            "uptime_pct": global_stats.uptime_pct,
            "best_node": global_stats.best_node,
            "worst_node": global_stats.worst_node,
            "longest_outage_node": global_stats.longest_outage_node,
            "longest_outage_ticks": global_stats.longest_outage_ticks,
        },
        "nodes": [
            {
                "url": s.url,
                "region": s.region,
                "total": s.total,
                "ok": s.ok,
                "uptime_pct": s.uptime_pct,
                "errors": s.errors,
                "latency_ms": {
                    "avg": s.latency.avg_ms,
                    "min": s.latency.min_ms,
                    "max": s.latency.max_ms,
                    "p95": s.latency.p95_ms,
                },
                "error_classes": s.error_classes,
            }
            for s in sorted(per_node.values(), key=lambda x: x.url)
        ],
    }


def node_stats_to_dict(s: NodeStats) -> dict:
    """Convenience for tests and debug dumps."""
    return asdict(s)
