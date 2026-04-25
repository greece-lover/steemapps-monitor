"""Observation engine — turn aggregated stats into prose.

Pure functions. No I/O, no clock. The caller assembles the inputs from
`reporter.aggregation` and a few day-window queries, hands them in, and
gets back a list of Observation objects ready to render.

Categories are pinned in the CATEGORY_* constants. Each `gather_*` helper
returns at most one Observation; the top-level `gather_observations`
calls them in priority order so the most newsworthy items come first.

When the prerequisite data for a category is missing — e.g. no yesterday
stats for a latency-change comparison — the corresponding helper returns
None instead of inventing a number. The intent is to keep the report
honest on day-1 of a node's life.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from reporter.aggregation import GlobalStats, NodeStats


# Prerequisite for a "consistent leader/laggard" observation. Without
# enough days of history a 1-week claim is statistical noise, so we
# require the full week of per-day stats before either fires.
WEEK_HISTORY_MIN_DAYS = 7

# Threshold (milliseconds) for flagging a single node's day-over-day
# latency move as "notable". Anything below this is normal jitter for
# a Steem JSON-RPC call.
LATENCY_CHANGE_THRESHOLD_MS = 100

# Threshold for a global trend observation (median across all nodes).
# Smaller than the per-node threshold because moves of the median tend
# to be less extreme than the per-node max move.
GLOBAL_TREND_THRESHOLD_MS = 30


# Severity tags drive the rendering style — green/orange/red bullet on
# the dashboard, neutral wording elsewhere. Kept as bare strings so the
# template can read them without importing the enum.
SEVERITY_POSITIVE = "positive"
SEVERITY_NEUTRAL = "neutral"
SEVERITY_NEGATIVE = "negative"


CATEGORY_TOP_PERFORMER = "top_performer"
CATEGORY_LAGGARD = "laggard"
CATEGORY_LATENCY_CHANGE = "latency_change"
CATEGORY_NEW_OUTAGE = "new_outage"
CATEGORY_CONSISTENT_LEADER = "consistent_leader"
CATEGORY_CONSISTENT_LAGGARD = "consistent_laggard"
CATEGORY_GLOBAL_TREND = "global_trend"
CATEGORY_BIGGEST_OUTAGE = "biggest_outage"


@dataclass(frozen=True)
class Observation:
    category: str
    severity: str
    headline: str
    detail: str = ""
    nodes: list[str] = field(default_factory=list)


# -----------------------------------------------------------------
#  Helpers
# -----------------------------------------------------------------


def _short(url: str) -> str:
    """Strip the protocol so the report copy is compact."""
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


def _median(values: list[int]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _by_avg_latency(stats: NodeStats) -> int:
    """Sort key — None latencies sink to the bottom."""
    return stats.latency.avg_ms if stats.latency.avg_ms is not None else 10**9


def _today_avg_latency(per_node: dict[str, NodeStats]) -> dict[str, int]:
    """Snapshot of {url: avg_ms} for nodes that have a measurable average.

    Nodes with no successful tick (avg_ms is None) are dropped — comparing
    them to any other latency would be meaningless."""
    return {
        url: s.latency.avg_ms
        for url, s in per_node.items()
        if s.latency.avg_ms is not None
    }


# -----------------------------------------------------------------
#  Per-category gatherers
# -----------------------------------------------------------------


def gather_top_performer(today_per_node: dict[str, NodeStats]) -> Optional[Observation]:
    """Fastest node today — by average latency over successful ticks.

    Headlines start with a `Label:` prefix so the template can bold the
    label uniformly across categories without per-category branching."""
    avgs = _today_avg_latency(today_per_node)
    if not avgs:
        return None
    fastest_url = min(avgs, key=avgs.get)
    fastest_ms = avgs[fastest_url]
    fleet_avg = sum(avgs.values()) / len(avgs)
    diff = fleet_avg - fastest_ms
    return Observation(
        category=CATEGORY_TOP_PERFORMER,
        severity=SEVERITY_POSITIVE,
        headline=f"Fastest node: `{_short(fastest_url)}` at {fastest_ms} ms average.",
        detail=f"That is {diff:.0f} ms below the fleet average of {fleet_avg:.0f} ms across {len(avgs)} nodes.",
        nodes=[fastest_url],
    )


def gather_laggard(today_per_node: dict[str, NodeStats]) -> Optional[Observation]:
    """Slowest node today by average latency."""
    avgs = _today_avg_latency(today_per_node)
    if len(avgs) < 2:
        return None
    slowest_url = max(avgs, key=avgs.get)
    slowest_ms = avgs[slowest_url]
    fleet_avg = sum(avgs.values()) / len(avgs)
    diff = slowest_ms - fleet_avg
    return Observation(
        category=CATEGORY_LAGGARD,
        severity=SEVERITY_NEGATIVE if diff > LATENCY_CHANGE_THRESHOLD_MS else SEVERITY_NEUTRAL,
        headline=f"Slowest node: `{_short(slowest_url)}` at {slowest_ms} ms average.",
        detail=f"That is {diff:.0f} ms above the fleet average of {fleet_avg:.0f} ms.",
        nodes=[slowest_url],
    )


def gather_latency_changes(
    today: dict[str, NodeStats],
    yesterday: dict[str, NodeStats],
) -> list[Observation]:
    """Per-node day-over-day latency moves above LATENCY_CHANGE_THRESHOLD_MS.

    Returns one Observation per affected node, sorted by absolute delta
    descending so the biggest movers come first."""
    if not yesterday:
        return []
    today_avgs = _today_avg_latency(today)
    yday_avgs = _today_avg_latency(yesterday)
    moves: list[tuple[str, int, int]] = []  # (url, delta, today_ms)
    for url, today_ms in today_avgs.items():
        yday_ms = yday_avgs.get(url)
        if yday_ms is None:
            continue
        delta = today_ms - yday_ms
        if abs(delta) >= LATENCY_CHANGE_THRESHOLD_MS:
            moves.append((url, delta, today_ms))
    moves.sort(key=lambda t: -abs(t[1]))
    out: list[Observation] = []
    for url, delta, today_ms in moves:
        improving = delta < 0
        word = "improved" if improving else "slowed"
        sign = "−" if improving else "+"
        out.append(Observation(
            category=CATEGORY_LATENCY_CHANGE,
            severity=SEVERITY_POSITIVE if improving else SEVERITY_NEGATIVE,
            headline=(
                f"Latency change: `{_short(url)}` {word} by {abs(delta)} ms vs. yesterday "
                f"({sign}{abs(delta)} ms; now {today_ms} ms average)."
            ),
            nodes=[url],
        ))
    return out


def gather_new_outages(
    today_per_node: dict[str, NodeStats],
    week_history: Optional[list[dict[str, NodeStats]]],
) -> list[Observation]:
    """Nodes that had a failed tick today AND zero failed ticks across the
    previous WEEK_HISTORY_MIN_DAYS days. Ignored when history is short."""
    if not week_history or len(week_history) < WEEK_HISTORY_MIN_DAYS:
        return []
    out: list[Observation] = []
    for url, today_stats in today_per_node.items():
        if today_stats.errors <= 0:
            continue
        had_prior_outage = any(
            (day.get(url) is not None and day[url].errors > 0)
            for day in week_history
        )
        if had_prior_outage:
            continue
        out.append(Observation(
            category=CATEGORY_NEW_OUTAGE,
            severity=SEVERITY_NEGATIVE,
            headline=(
                f"First failure in {WEEK_HISTORY_MIN_DAYS} days: `{_short(url)}` had "
                f"{today_stats.errors} failed tick{'s' if today_stats.errors != 1 else ''} today."
            ),
            nodes=[url],
        ))
    return out


def _node_appears_in_top_n_every_day(
    url: str,
    week_history: list[dict[str, NodeStats]],
    n: int,
    *,
    bottom: bool = False,
) -> bool:
    """Was the node in the top-N (or bottom-N) every single day in the window?"""
    for day in week_history:
        avgs = _today_avg_latency(day)
        if url not in avgs:
            return False
        ranked = sorted(avgs.items(), key=lambda kv: kv[1], reverse=bottom)
        top_urls = {u for u, _ in ranked[:n]}
        if url not in top_urls:
            return False
    return True


def gather_consistent_leaders(
    today_per_node: dict[str, NodeStats],
    week_history: Optional[list[dict[str, NodeStats]]],
) -> list[Observation]:
    """Nodes in the top-3-by-latency every single day for the past week."""
    if not week_history or len(week_history) < WEEK_HISTORY_MIN_DAYS:
        return []
    out: list[Observation] = []
    for url in today_per_node:
        if _node_appears_in_top_n_every_day(url, week_history, 3, bottom=False):
            out.append(Observation(
                category=CATEGORY_CONSISTENT_LEADER,
                severity=SEVERITY_POSITIVE,
                headline=f"Consistent leader: `{_short(url)}` has been in the top 3 by latency every day this week.",
                nodes=[url],
            ))
    return out


def gather_consistent_laggards(
    today_per_node: dict[str, NodeStats],
    week_history: Optional[list[dict[str, NodeStats]]],
) -> list[Observation]:
    """Nodes in the bottom-3-by-latency every single day for the past week."""
    if not week_history or len(week_history) < WEEK_HISTORY_MIN_DAYS:
        return []
    out: list[Observation] = []
    for url in today_per_node:
        if _node_appears_in_top_n_every_day(url, week_history, 3, bottom=True):
            out.append(Observation(
                category=CATEGORY_CONSISTENT_LAGGARD,
                severity=SEVERITY_NEGATIVE,
                headline=f"Consistent laggard: `{_short(url)}` has been in the bottom 3 by latency every day this week.",
                nodes=[url],
            ))
    return out


def gather_global_trend(
    today_per_node: dict[str, NodeStats],
    yesterday_per_node: Optional[dict[str, NodeStats]],
) -> Optional[Observation]:
    """Median-of-medians latency move across the whole fleet vs. yesterday."""
    if not yesterday_per_node:
        return None
    today_med = _median(list(_today_avg_latency(today_per_node).values()))
    yday_med = _median(list(_today_avg_latency(yesterday_per_node).values()))
    if today_med is None or yday_med is None:
        return None
    delta = today_med - yday_med
    if abs(delta) < GLOBAL_TREND_THRESHOLD_MS:
        return None
    improving = delta < 0
    sign = "−" if improving else "+"
    word = "improved" if improving else "regressed"
    return Observation(
        category=CATEGORY_GLOBAL_TREND,
        severity=SEVERITY_POSITIVE if improving else SEVERITY_NEGATIVE,
        headline=(
            f"Fleet trend: median latency {word} by {abs(delta):.0f} ms vs. yesterday "
            f"({sign}{abs(delta):.0f} ms; now {today_med:.0f} ms)."
        ),
        nodes=[],
    )


def gather_biggest_outage(global_stats: GlobalStats) -> Optional[Observation]:
    """Surface the longest single failure run as its own observation."""
    if not global_stats.longest_outage_node or global_stats.longest_outage_ticks <= 0:
        return None
    minutes = global_stats.longest_outage_ticks
    return Observation(
        category=CATEGORY_BIGGEST_OUTAGE,
        severity=SEVERITY_NEGATIVE,
        headline=(
            f"Longest outage today: `{_short(global_stats.longest_outage_node)}`, "
            f"{minutes} consecutive failed minute{'s' if minutes != 1 else ''}."
        ),
        nodes=[global_stats.longest_outage_node],
    )


# -----------------------------------------------------------------
#  Top-level
# -----------------------------------------------------------------


# Stable order — items earlier in this list appear first in the report.
# Within each category that returns a list we keep the per-helper sort.
_PRIORITY = [
    CATEGORY_BIGGEST_OUTAGE,
    CATEGORY_NEW_OUTAGE,
    CATEGORY_GLOBAL_TREND,
    CATEGORY_LATENCY_CHANGE,
    CATEGORY_TOP_PERFORMER,
    CATEGORY_LAGGARD,
    CATEGORY_CONSISTENT_LEADER,
    CATEGORY_CONSISTENT_LAGGARD,
]


def gather_observations(
    today_per_node: dict[str, NodeStats],
    today_global: GlobalStats,
    *,
    yesterday_per_node: Optional[dict[str, NodeStats]] = None,
    week_history: Optional[list[dict[str, NodeStats]]] = None,
) -> list[Observation]:
    """Build the full observation list for one report.

    `week_history` should be the list of seven prior daily aggregates,
    oldest first. None means "we do not have a week of data yet" and any
    week-anchored observation is silently skipped.
    """
    items: list[Observation] = []

    if (b := gather_biggest_outage(today_global)):
        items.append(b)
    items.extend(gather_new_outages(today_per_node, week_history))
    if (g := gather_global_trend(today_per_node, yesterday_per_node)):
        items.append(g)
    items.extend(gather_latency_changes(today_per_node, yesterday_per_node or {}))
    if (t := gather_top_performer(today_per_node)):
        items.append(t)
    if (l := gather_laggard(today_per_node)):
        items.append(l)
    items.extend(gather_consistent_leaders(today_per_node, week_history))
    items.extend(gather_consistent_laggards(today_per_node, week_history))

    # Re-sort to honour the priority list, in case future helpers append
    # in different orders.
    order = {cat: i for i, cat in enumerate(_PRIORITY)}
    items.sort(key=lambda o: order.get(o.category, 999))
    return items


# -----------------------------------------------------------------
#  Executive summary
# -----------------------------------------------------------------


def make_executive_summary(
    today_per_node: dict[str, NodeStats],
    today_global: GlobalStats,
    day: str,
) -> str:
    """Headline-only summary — uptime, node count, total measurements,
    median latency. No specific observations cited; those are surfaced in
    the bulleted Observations section. Three short sentences."""
    node_count = len(today_per_node)
    avgs = list(_today_avg_latency(today_per_node).values())
    median_ms = _median(avgs)
    median_clause = (
        f" Median latency across all nodes: {median_ms:.0f} ms."
        if median_ms is not None else ""
    )
    return (
        f"On {day} (UTC) the monitor tracked {node_count} Steem API node"
        f"{'s' if node_count != 1 else ''} with a global uptime of "
        f"{today_global.uptime_pct:.2f}% across "
        f"{today_global.total_measurements:,} measurements."
        f"{median_clause} Today's full picture and notable patterns below."
    )
