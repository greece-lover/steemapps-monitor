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
    p50_ms: Optional[int]
    p95_ms: Optional[int]
    p99_ms: Optional[int]


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
    # Number of distinct source_location values that contributed measurements
    # for this node within the window. Used by the report template to label
    # latency as "X ms (avg of N sources)" once external participants come
    # online; for the single-source baseline it stays at 1.
    source_count: int = 1


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


def _percentile(values: list[int], p: float) -> Optional[int]:
    """Nearest-rank percentile — good enough for a few thousand samples.

    Uses a sorted-list lookup rather than a heavy stats library; the report
    runs once a day over at most ~1440 samples per node, not a streaming
    workload. `p` is a 0..100 float (e.g. 95 for p95).
    """
    if not values:
        return None
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return int(s[idx])


def _p95(values: list[int]) -> Optional[int]:
    """Backwards-compatible shim. New code should use `_percentile`."""
    return _percentile(values, 95)


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
        p50_ms=_percentile(latencies, 50),
        p95_ms=_percentile(latencies, 95),
        p99_ms=_percentile(latencies, 99),
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
    sources = {r.get("source_location") for r in rows if r.get("source_location") is not None}
    return NodeStats(
        url=url,
        region=region,
        total=total,
        ok=ok,
        uptime_pct=round(uptime, 2),
        errors=errors,
        latency=lat,
        error_classes=classes,
        source_count=max(1, len(sources)),
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
    error_breakdown: Optional["ErrorBreakdown"] = None,
) -> dict:
    """Serialise the aggregates into the stable on-chain schema.

    Anyone consuming the `custom_json` operation downstream (Welako,
    third-party dashboards) can rely on these keys. A breaking change to
    the shape warrants a new operation id, not a silent format shift.

    `error_breakdown` is optional for backwards compatibility — when
    omitted the `error_breakdown` field is absent from the payload
    (rather than `null`), so old consumers see exactly what they used to.
    """
    summary = {
        "total_measurements": global_stats.total_measurements,
        "total_ok": global_stats.total_ok,
        "uptime_pct": global_stats.uptime_pct,
        "best_node": global_stats.best_node,
        "worst_node": global_stats.worst_node,
        "longest_outage_node": global_stats.longest_outage_node,
        "longest_outage_ticks": global_stats.longest_outage_ticks,
    }
    if error_breakdown is not None:
        summary["error_breakdown"] = {
            "total_errors": error_breakdown.total_errors,
            "top": [
                {"bucket": s.bucket, "count": s.count, "pct": s.pct}
                for s in error_breakdown.top
            ],
        }
    return {
        "version": methodology_version,
        "day": day,
        "window": {"start": window_start, "end": window_end},
        "source_location": source_location,
        "summary": summary,
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
                    "p50": s.latency.p50_ms,
                    "p95": s.latency.p95_ms,
                    "p99": s.latency.p99_ms,
                },
                "error_classes": s.error_classes,
                "source_count": s.source_count,
            }
            for s in sorted(per_node.values(), key=lambda x: x.url)
        ],
    }


def node_stats_to_dict(s: NodeStats) -> dict:
    """Convenience for tests and debug dumps."""
    return asdict(s)


# =============================================================================
#  Phase 6 Etappe 12a — extended aggregations for the daily report
# =============================================================================
#
# Each function below is pure and consumes the same row dicts that
# `query.fetch_measurements_in_window` returns. Schemas are exposed as
# frozen dataclasses so the template can pattern-match on attributes
# instead of dict keys (and so the type checker has something to work
# with at the boundary between aggregation and rendering).


# ---------------------------------------------------------------------------
#  A) Latency distribution buckets (cumulative thresholds)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatencyDistribution:
    """Cumulative-percent thresholds across all successful ticks in a window.

    The thresholds (200 / 500 / 1000 ms) are picked to match the bands
    a frontend operator cares about: <200 ms feels instant, <500 ms is
    snappy, <1000 ms is acceptable, beyond that users start noticing.
    """
    sample_size: int
    pct_under_200ms: float
    pct_under_500ms: float
    pct_under_1000ms: float
    pct_above_1000ms: float


def compute_latency_distribution(rows: list[dict]) -> LatencyDistribution:
    """Bucket all *successful* latencies into the four bands above."""
    latencies = [
        int(r["latency_ms"])
        for r in rows
        if r["success"] and r.get("latency_ms") is not None
    ]
    n = len(latencies)
    if n == 0:
        return LatencyDistribution(0, 0.0, 0.0, 0.0, 0.0)
    under_200 = sum(1 for l in latencies if l < 200)
    under_500 = sum(1 for l in latencies if l < 500)
    under_1000 = sum(1 for l in latencies if l < 1000)
    above_1000 = n - under_1000
    return LatencyDistribution(
        sample_size=n,
        pct_under_200ms=round(100.0 * under_200 / n, 1),
        pct_under_500ms=round(100.0 * under_500 / n, 1),
        pct_under_1000ms=round(100.0 * under_1000 / n, 1),
        pct_above_1000ms=round(100.0 * above_1000 / n, 1),
    )


# ---------------------------------------------------------------------------
#  B) Time-of-day pattern (best/worst UTC hour)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HourBucket:
    hour_utc: int                 # 0..23
    avg_latency_ms: Optional[int]
    sample_size: int


@dataclass(frozen=True)
class HourPattern:
    """24 buckets — best/worst extracted by avg latency among non-empty ones."""
    buckets: list[HourBucket]     # always length 24, ordered by hour
    best: Optional[HourBucket]    # lowest avg among populated hours
    worst: Optional[HourBucket]   # highest avg among populated hours


def compute_hour_pattern(rows: list[dict]) -> HourPattern:
    """Group successful ticks by UTC hour, build a 24-element series.

    Empty hours keep `avg_latency_ms=None` so the renderer can show the
    gap honestly instead of imputing zero. `best`/`worst` are picked from
    populated hours only (otherwise an empty hour would always 'win').
    """
    by_hour: dict[int, list[int]] = {h: [] for h in range(24)}
    for r in rows:
        if not r["success"] or r.get("latency_ms") is None:
            continue
        # ISO-8601 Z timestamp → hour. Cheap string slice — the timestamps
        # live in the canonical YYYY-MM-DDTHH:MM:SSZ shape (see
        # ingest.normalise_timestamp).
        try:
            hh = int(r["timestamp"][11:13])
        except (KeyError, ValueError, IndexError):
            continue
        if 0 <= hh < 24:
            by_hour[hh].append(int(r["latency_ms"]))
    buckets: list[HourBucket] = []
    for h in range(24):
        vals = by_hour[h]
        if vals:
            buckets.append(HourBucket(h, int(sum(vals) / len(vals)), len(vals)))
        else:
            buckets.append(HourBucket(h, None, 0))
    populated = [b for b in buckets if b.avg_latency_ms is not None]
    best = min(populated, key=lambda b: b.avg_latency_ms) if populated else None
    worst = max(populated, key=lambda b: b.avg_latency_ms) if populated else None
    return HourPattern(buckets=buckets, best=best, worst=worst)


# ---------------------------------------------------------------------------
#  C) Error pattern analysis (top error types with share)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ErrorTypeShare:
    bucket: str       # canonical label from `_error_bucket`
    count: int
    pct: float        # of total errors, 0..100


@dataclass(frozen=True)
class ErrorBreakdown:
    total_errors: int
    top: list[ErrorTypeShare]   # at most 3 entries, sorted desc by count


def compute_error_breakdown(per_node: dict[str, NodeStats], top_n: int = 3) -> ErrorBreakdown:
    """Sum up the error_classes counters across every node, return top-N."""
    totals: dict[str, int] = {}
    for s in per_node.values():
        for bucket, count in s.error_classes.items():
            totals[bucket] = totals.get(bucket, 0) + count
    grand = sum(totals.values())
    if grand == 0:
        return ErrorBreakdown(total_errors=0, top=[])
    ordered = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return ErrorBreakdown(
        total_errors=grand,
        top=[
            ErrorTypeShare(bucket=b, count=c, pct=round(100.0 * c / grand, 1))
            for b, c in ordered
        ],
    )


# ---------------------------------------------------------------------------
#  D) Best-vs-worst performance gap (today vs previous-week reference)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerformanceGap:
    today_fastest_ms: Optional[int]
    today_slowest_ms: Optional[int]
    today_factor: Optional[float]    # slowest / fastest
    prev_factor: Optional[float]     # same calculation, previous-week reference
    trend: str                       # "widening" | "narrowing" | "stable" | "no_history"


def compute_performance_gap(
    today_per_node: dict[str, NodeStats],
    prev_per_node: Optional[dict[str, NodeStats]],
    *,
    stable_threshold_pct: float = 10.0,
) -> PerformanceGap:
    """Spread between fastest and slowest avg latency, with a week-ago hint.

    `trend` is "widening" / "narrowing" if the today-factor is more than
    `stable_threshold_pct` away from the previous-week factor; "stable"
    if within that band; "no_history" if we have no comparable
    previous-week stats to anchor against.
    """
    def _factor(per_node: dict[str, NodeStats]) -> tuple[Optional[int], Optional[int], Optional[float]]:
        avgs = [s.latency.avg_ms for s in per_node.values() if s.latency.avg_ms is not None]
        if not avgs:
            return None, None, None
        fastest = min(avgs)
        slowest = max(avgs)
        if fastest <= 0:
            return fastest, slowest, None
        return fastest, slowest, round(slowest / fastest, 2)

    fastest, slowest, today_factor = _factor(today_per_node)
    prev_factor: Optional[float] = None
    trend = "no_history"
    if prev_per_node:
        _, _, prev_factor = _factor(prev_per_node)
    if today_factor is not None and prev_factor is not None and prev_factor > 0:
        change_pct = abs(today_factor - prev_factor) / prev_factor * 100.0
        if change_pct < stable_threshold_pct:
            trend = "stable"
        elif today_factor > prev_factor:
            trend = "widening"
        else:
            trend = "narrowing"
    return PerformanceGap(
        today_fastest_ms=fastest,
        today_slowest_ms=slowest,
        today_factor=today_factor,
        prev_factor=prev_factor,
        trend=trend,
    )


# ---------------------------------------------------------------------------
#  E) Cross-region latency variance (multi-source only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossRegionEntry:
    node_url: str
    # region (string) → avg_latency_ms across that region's source(s).
    by_region: dict[str, int]
    variance_factor: float       # max(by_region) / min(by_region)


@dataclass(frozen=True)
class CrossRegionResult:
    """Per-node latency by source region. Only nodes seen from at least
    two distinct source regions appear in `entries`."""
    entries: list[CrossRegionEntry]


def compute_cross_region_variance(
    rows_by_node: dict[str, list[dict]],
    source_to_region: dict[str, str],
) -> CrossRegionResult:
    """Group successful ticks by (node, source-region), compute avg per group.

    `source_to_region` maps the `source_location` string the monitor and
    participants write into the rows to the source's geographic region
    string. Sources missing from the map (e.g. legacy 'demo' rows from
    --seed-synthetic) are simply skipped.
    """
    entries: list[CrossRegionEntry] = []
    for url, rows in rows_by_node.items():
        # Group by (region) → list of latencies.
        by_region_lats: dict[str, list[int]] = {}
        for r in rows:
            if not r["success"] or r.get("latency_ms") is None:
                continue
            src = r.get("source_location")
            if not src:
                continue
            region = source_to_region.get(src)
            if not region:
                continue
            by_region_lats.setdefault(region, []).append(int(r["latency_ms"]))
        # Need at least 2 distinct regions to compute variance.
        if len(by_region_lats) < 2:
            continue
        by_region_avg = {
            region: int(sum(lats) / len(lats))
            for region, lats in by_region_lats.items()
            if lats
        }
        if len(by_region_avg) < 2:
            continue
        lo = min(by_region_avg.values())
        hi = max(by_region_avg.values())
        if lo <= 0:
            continue
        entries.append(CrossRegionEntry(
            node_url=url,
            by_region=by_region_avg,
            variance_factor=round(hi / lo, 2),
        ))
    # Sort by variance descending so the most surprising nodes come first.
    entries.sort(key=lambda e: e.variance_factor, reverse=True)
    return CrossRegionResult(entries=entries)


# ---------------------------------------------------------------------------
#  F) Multi-day reliability ranking (dynamic window)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReliabilityEntry:
    node_url: str
    uptime_pct: float
    sample_size: int


@dataclass(frozen=True)
class ReliabilityRanking:
    """Top/bottom uptime over a dynamic-length history window.

    `days_actual` is the actual span the ranking covers, which may be
    less than the requested 30 if the monitor has not been running that
    long yet. `longest_streak_days` is the longest unbroken run of all-
    successful days for the streak-leader node.
    """
    days_actual: int
    top: list[ReliabilityEntry]              # up to 3, best first
    bottom: list[ReliabilityEntry]           # up to 3, worst first
    longest_streak_node: Optional[str]
    longest_streak_days: int


def compute_reliability_ranking(
    daily_rows_by_node: list[dict[str, list[dict]]],
    *,
    top_n: int = 3,
    min_rows_per_day: int = 100,
) -> ReliabilityRanking:
    """Aggregate uptime over a list of per-day row groupings.

    `daily_rows_by_node` is a list of `{node_url: [rows]}` dicts, one per
    day, oldest first. A day's per-node entry counts toward the streak
    only if it has at least `min_rows_per_day` rows AND every row was a
    success — that keeps a partial-coverage day from inflating a streak.
    """
    days_actual = len(daily_rows_by_node)
    if days_actual == 0:
        return ReliabilityRanking(
            days_actual=0, top=[], bottom=[],
            longest_streak_node=None, longest_streak_days=0,
        )

    # Aggregate uptime per node across all days.
    union_urls: set[str] = set()
    for day in daily_rows_by_node:
        union_urls.update(day.keys())
    overall: list[ReliabilityEntry] = []
    for url in union_urls:
        total = 0
        ok = 0
        for day in daily_rows_by_node:
            for r in day.get(url, []):
                total += 1
                if r["success"]:
                    ok += 1
        if total < min_rows_per_day:
            continue
        overall.append(ReliabilityEntry(
            node_url=url,
            uptime_pct=round(100.0 * ok / total, 2),
            sample_size=total,
        ))
    overall.sort(key=lambda e: e.uptime_pct, reverse=True)
    top = overall[:top_n]
    bottom = list(reversed(overall[-top_n:])) if len(overall) >= top_n else list(reversed(overall))

    # Longest unbroken streak: per node, walk the days oldest→newest,
    # bump the run on a clean day, reset on any failure or coverage hole.
    longest_node: Optional[str] = None
    longest_run = 0
    for url in union_urls:
        run = 0
        node_best = 0
        for day in daily_rows_by_node:
            day_rows = day.get(url, [])
            if len(day_rows) < min_rows_per_day:
                run = 0
                continue
            day_failed = any(not r["success"] for r in day_rows)
            if day_failed:
                run = 0
            else:
                run += 1
                node_best = max(node_best, run)
        if node_best > longest_run:
            longest_run = node_best
            longest_node = url

    return ReliabilityRanking(
        days_actual=days_actual,
        top=top,
        bottom=bottom,
        longest_streak_node=longest_node,
        longest_streak_days=longest_run,
    )
