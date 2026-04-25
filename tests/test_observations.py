"""Observation engine tests — one test per category, plus the executive
summary picker. All inputs are synthetic NodeStats / GlobalStats so the
tests stay independent of the DB and clock."""

from __future__ import annotations

from reporter import aggregation, observations
from reporter.aggregation import GlobalStats, LatencyStats, NodeStats


def _ns(url: str, *, avg: int | None, uptime: float = 100.0,
        errors: int = 0, region: str = "eu") -> NodeStats:
    return NodeStats(
        url=url, region=region, total=100,
        ok=int(100 * uptime / 100), uptime_pct=uptime,
        errors=errors,
        latency=LatencyStats(avg_ms=avg, min_ms=avg, max_ms=avg, p95_ms=avg),
    )


def _gs(*, longest_node: str | None = None, longest_ticks: int = 0) -> GlobalStats:
    return GlobalStats(
        total_measurements=100, total_ok=100, uptime_pct=100.0,
        best_node=None, worst_node=None,
        longest_outage_node=longest_node,
        longest_outage_ticks=longest_ticks,
    )


# =============================================================================
#  gather_top_performer / gather_laggard
# =============================================================================

def test_top_performer_picks_lowest_avg_latency():
    today = {
        "https://fast.example": _ns("https://fast.example", avg=100),
        "https://slow.example": _ns("https://slow.example", avg=500),
    }
    obs = observations.gather_top_performer(today)
    assert obs is not None
    assert obs.category == observations.CATEGORY_TOP_PERFORMER
    assert "fast.example" in obs.headline
    assert "100 ms" in obs.headline
    assert obs.severity == observations.SEVERITY_POSITIVE


def test_top_performer_returns_none_with_no_measurable_avg():
    today = {"https://x.example": _ns("https://x.example", avg=None)}
    assert observations.gather_top_performer(today) is None


def test_laggard_picks_highest_avg_latency():
    today = {
        "https://fast.example": _ns("https://fast.example", avg=100),
        "https://slow.example": _ns("https://slow.example", avg=500),
    }
    obs = observations.gather_laggard(today)
    assert obs is not None
    assert obs.category == observations.CATEGORY_LAGGARD
    assert "slow.example" in obs.headline


def test_laggard_returns_none_with_only_one_node():
    today = {"https://only.example": _ns("https://only.example", avg=100)}
    assert observations.gather_laggard(today) is None


# =============================================================================
#  gather_latency_changes
# =============================================================================

def test_latency_change_fires_when_delta_above_threshold():
    today = {"https://x.example": _ns("https://x.example", avg=300)}
    yday  = {"https://x.example": _ns("https://x.example", avg=180)}
    obs = observations.gather_latency_changes(today, yday)
    assert len(obs) == 1
    assert obs[0].category == observations.CATEGORY_LATENCY_CHANGE
    assert obs[0].severity == observations.SEVERITY_NEGATIVE
    assert obs[0].headline.startswith("Latency change:")
    assert "120 ms" in obs[0].headline
    assert "slowed" in obs[0].headline


def test_latency_change_below_threshold_silent():
    today = {"https://x.example": _ns("https://x.example", avg=200)}
    yday  = {"https://x.example": _ns("https://x.example", avg=180)}
    assert observations.gather_latency_changes(today, yday) == []


def test_latency_change_improvement_marked_positive():
    today = {"https://x.example": _ns("https://x.example", avg=180)}
    yday  = {"https://x.example": _ns("https://x.example", avg=350)}
    obs = observations.gather_latency_changes(today, yday)
    assert obs[0].severity == observations.SEVERITY_POSITIVE
    assert "improved" in obs[0].headline


def test_latency_change_no_yesterday_returns_empty():
    today = {"https://x.example": _ns("https://x.example", avg=200)}
    assert observations.gather_latency_changes(today, {}) == []


# =============================================================================
#  gather_new_outages
# =============================================================================

def test_new_outage_fires_when_no_failures_in_prior_week():
    today = {"https://x.example": _ns("https://x.example", avg=200, errors=2, uptime=98.0)}
    week = [{"https://x.example": _ns("https://x.example", avg=200, errors=0, uptime=100.0)}
            for _ in range(7)]
    obs = observations.gather_new_outages(today, week)
    assert len(obs) == 1
    assert obs[0].category == observations.CATEGORY_NEW_OUTAGE
    assert obs[0].headline.startswith("First failure in 7 days:")


def test_new_outage_silent_when_node_failed_in_week():
    today = {"https://x.example": _ns("https://x.example", avg=200, errors=2, uptime=98.0)}
    week = [{"https://x.example": _ns("https://x.example", avg=200,
                                      errors=0 if i < 6 else 1, uptime=99.9)}
            for i in range(7)]
    assert observations.gather_new_outages(today, week) == []


def test_new_outage_silent_when_history_too_short():
    today = {"https://x.example": _ns("https://x.example", avg=200, errors=2)}
    week = [{"https://x.example": _ns("https://x.example", avg=200, errors=0)}
            for _ in range(3)]
    assert observations.gather_new_outages(today, week) == []


# =============================================================================
#  gather_consistent_leaders / consistent_laggards
# =============================================================================

def _week_with_node_at_position(url: str, position: int, *, n_nodes: int = 6) -> list[dict[str, NodeStats]]:
    """Build a 7-day history where `url` sits at `position` in the latency
    ranking every day (0 = fastest)."""
    others = [f"https://other{i}.example" for i in range(n_nodes - 1)]
    week = []
    for _ in range(7):
        latencies = [100, 150, 200, 250, 300, 350, 400, 450, 500][:n_nodes]
        ranked_urls = others.copy()
        ranked_urls.insert(position, url)
        day = {u: _ns(u, avg=lat) for u, lat in zip(ranked_urls, latencies)}
        week.append(day)
    return week


def test_consistent_leader_fires_when_in_top_3_every_day():
    today = {"https://x.example": _ns("https://x.example", avg=100)}
    week = _week_with_node_at_position("https://x.example", position=0)
    obs = observations.gather_consistent_leaders(today, week)
    assert any(o.category == observations.CATEGORY_CONSISTENT_LEADER for o in obs)
    leader = next(o for o in obs if o.category == observations.CATEGORY_CONSISTENT_LEADER)
    assert leader.headline.startswith("Consistent leader:")


def test_consistent_leader_silent_when_dropped_one_day():
    today = {"https://x.example": _ns("https://x.example", avg=100)}
    week = _week_with_node_at_position("https://x.example", position=0)
    # On one day push it to position 5 — out of top-3.
    week[3] = _week_with_node_at_position("https://x.example", position=5)[0]
    assert observations.gather_consistent_leaders(today, week) == []


def test_consistent_laggard_fires_when_in_bottom_3_every_day():
    today = {"https://x.example": _ns("https://x.example", avg=500)}
    # Rank 5 in a 6-node fleet = bottom-2.
    week = _week_with_node_at_position("https://x.example", position=5, n_nodes=6)
    obs = observations.gather_consistent_laggards(today, week)
    assert any(o.category == observations.CATEGORY_CONSISTENT_LAGGARD for o in obs)
    laggard = next(o for o in obs if o.category == observations.CATEGORY_CONSISTENT_LAGGARD)
    assert laggard.headline.startswith("Consistent laggard:")


# =============================================================================
#  gather_global_trend
# =============================================================================

def test_global_trend_fires_when_median_moves():
    today = {f"https://n{i}.example": _ns(f"https://n{i}.example", avg=300) for i in range(5)}
    yday  = {f"https://n{i}.example": _ns(f"https://n{i}.example", avg=200) for i in range(5)}
    obs = observations.gather_global_trend(today, yday)
    assert obs is not None
    assert obs.category == observations.CATEGORY_GLOBAL_TREND
    assert obs.severity == observations.SEVERITY_NEGATIVE
    assert obs.headline.startswith("Fleet trend:")
    assert "100" in obs.headline


def test_global_trend_silent_below_threshold():
    today = {f"https://n{i}.example": _ns(f"https://n{i}.example", avg=210) for i in range(5)}
    yday  = {f"https://n{i}.example": _ns(f"https://n{i}.example", avg=200) for i in range(5)}
    assert observations.gather_global_trend(today, yday) is None


def test_global_trend_silent_without_yesterday():
    today = {"https://x.example": _ns("https://x.example", avg=200)}
    assert observations.gather_global_trend(today, None) is None


# =============================================================================
#  gather_biggest_outage
# =============================================================================

def test_biggest_outage_fires_when_global_stats_has_one():
    gs = _gs(longest_node="https://broken.example", longest_ticks=12)
    obs = observations.gather_biggest_outage(gs)
    assert obs is not None
    assert obs.category == observations.CATEGORY_BIGGEST_OUTAGE
    assert "12 consecutive failed minutes" in obs.headline
    assert obs.severity == observations.SEVERITY_NEGATIVE


def test_biggest_outage_silent_when_no_outage():
    assert observations.gather_biggest_outage(_gs()) is None


# =============================================================================
#  gather_observations top-level + executive summary
# =============================================================================

def test_gather_observations_orders_by_priority():
    """Biggest outage and new outage land before consistent leaders."""
    today = {
        "https://x.example": _ns("https://x.example", avg=200, errors=1, uptime=99.0),
        "https://y.example": _ns("https://y.example", avg=300),
    }
    week = [{"https://x.example": _ns("https://x.example", avg=200, errors=0)} for _ in range(7)]
    gs = _gs(longest_node="https://x.example", longest_ticks=5)
    items = observations.gather_observations(today, gs,
                                              yesterday_per_node=None,
                                              week_history=week)
    cats = [o.category for o in items]
    # CATEGORY_BIGGEST_OUTAGE first, then CATEGORY_NEW_OUTAGE.
    assert cats.index(observations.CATEGORY_BIGGEST_OUTAGE) < \
           cats.index(observations.CATEGORY_NEW_OUTAGE)


def test_executive_summary_includes_headline_numbers():
    gs = GlobalStats(
        total_measurements=14400, total_ok=14380, uptime_pct=99.86,
        best_node=None, worst_node=None,
        longest_outage_node=None, longest_outage_ticks=0,
    )
    today = {f"https://n{i}.example": _ns(f"https://n{i}.example", avg=200 + i * 50)
             for i in range(10)}
    summary = observations.make_executive_summary(today, gs, day="2026-04-24")
    assert "10 Steem API node" in summary
    # Uptime is rendered without space before %, with thousands separator.
    assert "99.86%" in summary
    assert "14,400 measurements" in summary
    # Median is computed from per_node and surfaces in the summary.
    assert "Median latency across all nodes:" in summary
    # Closing pointer to the rest of the post.
    assert "Today's full picture and notable patterns below." in summary


def test_executive_summary_omits_observations():
    """Spec: the summary cites only uptime, count, measurements, median.
    Specific observations belong to the bulleted section below."""
    gs = _gs(longest_node="https://broken.example", longest_ticks=12)
    today = {"https://x.example": _ns("https://x.example", avg=200)}
    summary = observations.make_executive_summary(today, gs, day="2026-04-24")
    # The biggest-outage detail does NOT leak into the summary.
    assert "Longest outage" not in summary
    assert "broken.example" not in summary
    assert "consecutive" not in summary
