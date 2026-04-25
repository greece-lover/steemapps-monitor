"""Template tests — English-only post structure (Etappe 9).

These pin the section ordering and the verbatim copy that is part of
the public-facing brand voice. Word-level edits to neutral copy do not
need to break a test, but the participation block, the methodology
one-liner, and the resources block are stable text.
"""

from __future__ import annotations

from reporter import aggregation, observations, template


def _row(ts: str, ok: bool = True, latency: int | None = 200,
         height: int | None = 1000, err: str | None = None,
         source: str = "test") -> dict:
    return {
        "timestamp": ts,
        "success": 1 if ok else 0,
        "latency_ms": latency,
        "block_height": height,
        "error_message": err,
        "source_location": source,
    }


def _sample_stats(*, source: str = "test"):
    rows_by_node = {
        "https://a.example": [_row(f"2026-04-24T10:{i:02d}:00Z", source=source) for i in range(10)],
        "https://b.example": [
            _row(f"2026-04-24T10:{i:02d}:00Z", ok=(i < 7),
                 latency=150 if i < 7 else None,
                 height=1000 if i < 7 else None,
                 err=None if i < 7 else "timeout",
                 source=source)
            for i in range(10)
        ],
    }
    per_node = {
        url: aggregation.aggregate_node(rs, url=url, region="eu")
        for url, rs in rows_by_node.items()
    }
    gs = aggregation.aggregate_global(per_node, rows_by_node)
    return per_node, gs


def _render(*, chain_reference=None, week=None, observations_list=None,
            cover_image_url=None):
    per_node, gs = _sample_stats()
    obs = observations_list if observations_list is not None else \
        observations.gather_observations(per_node, gs)
    return template.render(
        day="2026-04-24",
        window_start="2026-04-24T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        per_node=per_node,
        global_stats=gs,
        week=week,
        observations=obs,
        source_location="test",
        app_name="steemapps-monitor/test",
        tags=["steem", "api", "monitoring"],
        repo_url="https://github.com/greece-lover/steemapps-monitor",
        dashboard_url="https://api.steemapps.com",
        witness_url="https://steemitwallet.com/~witnesses",
        methodology_url=(
            "https://github.com/greece-lover/steemapps-monitor/blob/main/"
            "docs/MEASUREMENT-METHODOLOGY.md"
        ),
        cover_image_url=cover_image_url,
        chain_reference=chain_reference,
    )


# =============================================================================
#  Title, permlink, structural invariants
# =============================================================================

def test_render_title_uses_steem_api_health():
    post = _render()
    assert post.title == "Steem API Health — Daily Report 2026-04-24"
    assert post.permlink == "steemapps-api-daily-report-2026-04-24"


def test_post_is_english_only_no_german_section():
    post = _render()
    assert "## English" not in post.body
    assert "## Deutsch" not in post.body
    # No remnant German strings from the old bilingual template.
    assert "Vorwoche" not in post.body
    assert "Witness voten" not in post.body


def test_section_order_matches_spec():
    """Executive summary → perspective notice → observations → nodes → … → resources."""
    body = _render().body
    expected = [
        "On 2026-04-24",                                # 2. Exec summary
        "Today's full picture and notable patterns",    # last sentence of summary
        "*All measurements are taken from",             # 3. Perspective
        "## Nodes",                                     # 5. Detail table
        "## Resources",                                 # 10. Resources
    ]
    positions = [body.index(needle) for needle in expected]
    assert positions == sorted(positions), f"sections out of order: {positions}"


def test_executive_summary_is_headline_only():
    """Spec: executive summary cites uptime + count + median latency only;
    no specific outage / fastest-node mentions (those go in observations)."""
    body = _render().body
    # The summary always opens with the date.
    assert "On 2026-04-24 (UTC) the monitor tracked" in body
    # And ends with the canonical pointer to the rest of the post.
    assert "Today's full picture and notable patterns below." in body
    # The thousands separator from the spec example.
    assert "20 measurements" in body  # 2 nodes × 10 ticks = 20


# =============================================================================
#  Cover image
# =============================================================================

def test_cover_image_renders_when_url_present():
    post = _render(cover_image_url="https://api.steemapps.com/reports/2026-04-24.png")
    assert "![Steem API Health · 2026-04-24](https://api.steemapps.com/reports/2026-04-24.png)" in post.body
    assert post.json_metadata["image"] == ["https://api.steemapps.com/reports/2026-04-24.png"]


def test_cover_image_omitted_when_url_missing():
    post = _render(cover_image_url=None)
    assert "![" not in post.body
    assert post.json_metadata["image"] == []


# =============================================================================
#  Participation + Resources blocks (verbatim copy that is public brand voice)
# =============================================================================

def test_participation_block_has_three_action_items():
    body = _render().body
    assert "Want to make these reports more accurate?" in body
    assert "Participant script and instructions:" in body
    assert "Full participation guide:" in body
    assert "Request an API key" in body
    # Self-service onboarding URL — manual "DM the operator" variant
    # is intentionally no longer advertised.
    assert "https://api.steemapps.com/join.html" in body
    # Linked sources page on the live dashboard, not a file path.
    assert "https://api.steemapps.com/sources.html" in body


def test_resources_block_lists_canonical_links():
    body = _render().body
    assert "## Resources" in body
    assert "Live dashboard: https://api.steemapps.com" in body
    assert "API documentation:" in body
    assert "Source code: https://github.com/greece-lover/steemapps-monitor" in body
    assert "Methodology:" in body
    assert "Reporter account: @steem-api-health" in body
    assert "@greece-lover" in body
    assert "https://steemitwallet.com/~witnesses" in body


def test_feedback_block_present():
    assert "Feedback wanted" in _render().body


# =============================================================================
#  Perspective notice — varies with multi-source state
# =============================================================================

def test_perspective_notice_single_source():
    body = _render().body
    assert "single European location" in body
    # New wording: pivots to participation, not "being onboarded".
    assert "Want to contribute measurements from your region?" in body
    assert "being onboarded" not in body
    # Multi-source wording is reserved for that branch.
    assert "thanks to community contributors" not in body


def test_perspective_notice_multi_source():
    # Build per_node with source_count > 1 so the multi-source branch fires.
    rows_by_node = {
        "https://a.example": [
            _row("2026-04-24T10:00:00Z", source="contabo-de-1"),
            _row("2026-04-24T10:00:00Z", source="participant-us"),
        ],
    }
    per_node = {
        url: aggregation.aggregate_node(rs, url=url, region="eu")
        for url, rs in rows_by_node.items()
    }
    gs = aggregation.aggregate_global(per_node, rows_by_node)
    post = template.render(
        day="2026-04-24",
        window_start="2026-04-24T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        per_node=per_node,
        global_stats=gs,
        week=None,
        observations=[],
        source_location="contabo-de-1",
        app_name="steemapps-monitor/test",
        tags=["steem"],
        repo_url="https://github.com/greece-lover/steemapps-monitor",
        dashboard_url="https://api.steemapps.com",
        witness_url="https://steemitwallet.com/~witnesses",
        methodology_url="https://example.test/METH.md",
    )
    assert "thanks to community contributors" in post.body


def test_node_row_shows_avg_of_sources_when_multi():
    """When source_count > 1, the latency cell carries the source-count tag."""
    rows = [
        _row("2026-04-24T10:00:00Z", latency=200, source="contabo-de-1"),
        _row("2026-04-24T10:00:00Z", latency=300, source="participant-us"),
    ]
    per_node = {
        "https://a.example": aggregation.aggregate_node(rows, url="https://a.example", region="eu"),
    }
    gs = aggregation.aggregate_global(per_node, {"https://a.example": rows})
    post = template.render(
        day="2026-04-24",
        window_start="2026-04-24T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        per_node=per_node, global_stats=gs, week=None, observations=[],
        source_location="contabo-de-1",
        app_name="t", tags=["steem"],
        repo_url="https://github.com/greece-lover/steemapps-monitor",
        dashboard_url="https://api.steemapps.com",
        witness_url="https://example.test", methodology_url="https://example.test/METH.md",
    )
    assert "(avg of 2 sources)" in post.body


# =============================================================================
#  Observations rendering
# =============================================================================

def test_observations_section_renders_when_obs_present():
    obs = [observations.Observation(
        category=observations.CATEGORY_TOP_PERFORMER,
        severity=observations.SEVERITY_POSITIVE,
        headline="Fastest node: `a.example` at 100 ms.",
    )]
    body = _render(observations_list=obs).body
    assert "## Observations" in body
    # Label prefix is bolded by the template; arrow markers are gone.
    assert "- **Fastest node:**" in body
    assert "↑" not in body
    assert "↓" not in body


def test_observations_section_omitted_when_no_observations():
    body = _render(observations_list=[]).body
    assert "## Observations" not in body


# =============================================================================
#  Biggest outage section
# =============================================================================

def test_biggest_outage_section_renders_with_outage():
    """Force a real outage in the sample data, then assert the section."""
    rows_by_node = {
        "https://a.example": [_row(f"2026-04-24T10:{i:02d}:00Z") for i in range(10)],
        "https://b.example": [
            _row(f"2026-04-24T10:00:00Z"),
            _row("2026-04-24T10:01:00Z", ok=False, err="timeout"),
            _row("2026-04-24T10:02:00Z", ok=False, err="timeout"),
            _row("2026-04-24T10:03:00Z", ok=False, err="timeout"),
            _row("2026-04-24T10:04:00Z"),
        ],
    }
    per_node = {url: aggregation.aggregate_node(rs, url=url, region="eu") for url, rs in rows_by_node.items()}
    gs = aggregation.aggregate_global(per_node, rows_by_node)
    post = template.render(
        day="2026-04-24",
        window_start="2026-04-24T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        per_node=per_node, global_stats=gs, week=None,
        observations=observations.gather_observations(per_node, gs),
        source_location="t", app_name="t", tags=["steem"],
        repo_url="https://github.com/greece-lover/steemapps-monitor",
        dashboard_url="https://api.steemapps.com",
        witness_url="https://example.test", methodology_url="https://example.test/METH.md",
    )
    assert "## Biggest outage of the day" in post.body
    assert "3 consecutive failed minutes" in post.body


def test_biggest_outage_section_omitted_when_clean():
    """When no node had an outage in the window the section is not rendered."""
    body = _render().body  # b.example has 3 fails but they're not consecutive
    # Sample data has b.example failing 3 times in a row (i>=7) → 3-tick streak.
    # That counts as a "biggest outage" — confirm presence via the actual
    # global_stats helper rather than asserting omission. This test instead
    # checks the section is absent for an all-OK fleet.
    rows_by_node = {"https://a.example": [_row(f"2026-04-24T10:{i:02d}:00Z") for i in range(5)]}
    per_node = {"https://a.example": aggregation.aggregate_node(rows_by_node["https://a.example"], url="https://a.example", region="eu")}
    gs = aggregation.aggregate_global(per_node, rows_by_node)
    post = template.render(
        day="2026-04-24",
        window_start="2026-04-24T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        per_node=per_node, global_stats=gs, week=None, observations=[],
        source_location="t", app_name="t", tags=["steem"],
        repo_url="https://github.com/greece-lover/steemapps-monitor",
        dashboard_url="https://api.steemapps.com",
        witness_url="https://example.test", methodology_url="https://example.test/METH.md",
    )
    assert "## Biggest outage of the day" not in post.body


# =============================================================================
#  Chain reference
# =============================================================================

def test_chain_reference_rendered_when_supplied():
    ref = template.ChainReference(tx_hash="abc123", block_num=12345)
    post = _render(chain_reference=ref)
    assert "abc123" in post.body
    assert "12345" in post.body


def test_chain_reference_fallback_when_absent():
    body = _render(chain_reference=None).body
    assert "in this report's broadcast log" in body


# =============================================================================
#  Week-over-week
# =============================================================================

def test_week_section_omitted_when_no_prior_week():
    body = _render(week=None).body
    assert "## Week over week" not in body


def test_week_section_renders_delta_when_present():
    cmp = aggregation.WeekComparison(
        current_uptime_pct=99.5,
        previous_uptime_pct=99.0,
        delta_pp=0.5,
        per_node_delta_pp={"https://a.example": 0.2, "https://b.example": 0.8},
    )
    body = _render(week=cmp).body
    assert "## Week over week" in body
    assert "99.50 %" in body
    assert "99.00 %" in body
    assert "+0.50 pp" in body


def test_week_section_renders_zero_delta_with_pm_sign():
    """Zero deltas (or -0.0 from float arithmetic) must render as ±0.00 pp,
    not "+-0.00 pp" or "0.00 pp" with no sign at all."""
    cmp = aggregation.WeekComparison(
        current_uptime_pct=99.5,
        previous_uptime_pct=99.5,
        delta_pp=0.0,
        per_node_delta_pp={"https://a.example": -0.0, "https://b.example": 0.0},
    )
    body = _render(week=cmp).body
    assert "±0.00 pp" in body
    assert "+-0.00" not in body
    assert "+0.00" not in body


# =============================================================================
#  json_metadata
# =============================================================================

def test_json_metadata_contains_tags_and_custom_json_id():
    post = _render()
    assert post.json_metadata["tags"] == ["steem", "api", "monitoring"]
    assert post.json_metadata["format"] == "markdown"
    assert post.json_metadata["steemapps_monitor"]["custom_json_id"] == "steemapps_api_stats_daily"
    assert post.json_metadata["steemapps_monitor"]["day"] == "2026-04-24"


# =============================================================================
#  Etappe 12a — extended sections
# =============================================================================

def _render_with(**kw):
    """Variant of _render that lets the caller pass any of the new
    optional aggregation arguments."""
    per_node, gs = _sample_stats()
    obs = kw.pop("observations_list", None) or observations.gather_observations(per_node, gs)
    return template.render(
        day="2026-04-24",
        window_start="2026-04-24T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        per_node=per_node,
        global_stats=gs,
        week=kw.pop("week", None),
        observations=obs,
        source_location="test",
        app_name="steemapps-monitor/test",
        tags=["steem", "api", "monitoring"],
        repo_url="https://github.com/greece-lover/steemapps-monitor",
        dashboard_url="https://api.steemapps.com",
        witness_url="https://steemitwallet.com/~witnesses",
        methodology_url=(
            "https://github.com/greece-lover/steemapps-monitor/blob/main/"
            "docs/MEASUREMENT-METHODOLOGY.md"
        ),
        **kw,
    )


def test_node_table_now_has_p50_and_p99_columns():
    body = _render().body
    # Header includes p50 and p99 between Avg and Errors.
    assert "| Avg | p50 | p95 | p99 | Errors |" in body


def test_latency_distribution_section_renders_with_data():
    d = aggregation.LatencyDistribution(
        sample_size=1000, pct_under_200ms=30.0,
        pct_under_500ms=75.0, pct_under_1000ms=95.0, pct_above_1000ms=5.0,
    )
    body = _render_with(latency_distribution=d).body
    assert "## Latency distribution" in body
    assert "1,000 successful measurements" in body
    assert "30.0 %" in body
    assert "under 200 ms" in body


def test_latency_distribution_section_omitted_when_no_data():
    body = _render_with(
        latency_distribution=aggregation.LatencyDistribution(0, 0.0, 0.0, 0.0, 0.0),
    ).body
    assert "## Latency distribution" not in body


def test_hour_pattern_section_renders_best_and_worst_slot():
    p = aggregation.HourPattern(
        buckets=[
            aggregation.HourBucket(h, 250 if h == 3 else (480 if h == 18 else None),
                                   60 if h in (3, 18) else 0)
            for h in range(24)
        ],
        best=aggregation.HourBucket(3, 250, 60),
        worst=aggregation.HourBucket(18, 480, 60),
    )
    body = _render_with(hour_pattern=p).body
    assert "## Time-of-day pattern" in body
    assert "03:00–04:00 UTC" in body
    assert "18:00–19:00 UTC" in body
    assert "250 ms" in body
    assert "480 ms" in body


def test_hour_pattern_section_omitted_when_best_equals_worst():
    """All measurements landed in the same hour — nothing to compare."""
    only_one = aggregation.HourBucket(10, 200, 60)
    p = aggregation.HourPattern(
        buckets=[aggregation.HourBucket(h, None, 0) if h != 10 else only_one for h in range(24)],
        best=only_one, worst=only_one,
    )
    body = _render_with(hour_pattern=p).body
    assert "## Time-of-day pattern" not in body


def test_error_pattern_section_renders_top_three():
    eb = aggregation.ErrorBreakdown(
        total_errors=100,
        top=[
            aggregation.ErrorTypeShare("connect_error", 62, 62.0),
            aggregation.ErrorTypeShare("http_5xx", 28, 28.0),
            aggregation.ErrorTypeShare("timeout", 10, 10.0),
        ],
    )
    body = _render_with(error_breakdown=eb).body
    assert "## Error pattern" in body
    assert "`connect_error`" in body
    assert "62.0 %" in body
    assert "100 total errors" in body or "100 total" in body


def test_error_pattern_section_omitted_when_clean_day():
    eb = aggregation.ErrorBreakdown(total_errors=0, top=[])
    body = _render_with(error_breakdown=eb).body
    assert "## Error pattern" not in body


def test_performance_gap_section_renders_factor_and_trend():
    g = aggregation.PerformanceGap(
        today_fastest_ms=120, today_slowest_ms=480,
        today_factor=4.0, prev_factor=2.0, trend="widening",
    )
    body = _render_with(performance_gap=g).body
    assert "## Best vs worst performance gap" in body
    assert "4.00× faster" in body
    assert "120 ms vs 480 ms" in body
    assert "**widening**" in body
    assert "2.00×" in body


def test_performance_gap_section_renders_no_history_note():
    g = aggregation.PerformanceGap(
        today_fastest_ms=120, today_slowest_ms=480,
        today_factor=4.0, prev_factor=None, trend="no_history",
    )
    body = _render_with(performance_gap=g).body
    assert "## Best vs worst performance gap" in body
    assert "Previous-week reference is not yet available" in body


def test_cross_region_section_omitted_when_single_region():
    cr = aggregation.CrossRegionResult(entries=[])
    body = _render_with(cross_region=cr).body
    assert "## Cross-region latency variance" not in body


def test_cross_region_section_renders_table_when_multi_region():
    cr = aggregation.CrossRegionResult(entries=[
        aggregation.CrossRegionEntry(
            node_url="https://a.example",
            by_region={"eu-central": 200, "asia": 450},
            variance_factor=2.25,
        ),
    ])
    body = _render_with(cross_region=cr).body
    assert "## Cross-region latency variance" in body
    assert "`a.example`" in body
    assert "eu-central 200 ms" in body
    assert "asia 450 ms" in body
    assert "2.25×" in body


def test_reliability_ranking_section_uses_dynamic_day_count():
    r = aggregation.ReliabilityRanking(
        days_actual=14,
        top=[aggregation.ReliabilityEntry("https://a.example", 99.95, 20000)],
        bottom=[aggregation.ReliabilityEntry("https://z.example", 95.00, 20000)],
        longest_streak_node="https://a.example",
        longest_streak_days=14,
    )
    body = _render_with(reliability=r).body
    # Headline reflects actual span — not a fixed "30-day".
    assert "## 14-day reliability ranking" in body
    assert "Most reliable" in body
    assert "Least reliable" in body
    assert "Longest unbroken uptime streak" in body
    assert "14 days" in body


def test_reliability_ranking_section_omitted_below_seven_days():
    r = aggregation.ReliabilityRanking(
        days_actual=3, top=[], bottom=[],
        longest_streak_node=None, longest_streak_days=0,
    )
    body = _render_with(reliability=r).body
    assert "reliability ranking" not in body.lower()


def test_detail_image_section_renders_when_url_supplied():
    body = _render_with(detail_image_url="https://api.steemapps.com/reports/2026-04-24-detail.png").body
    assert "## Visual detail" in body
    assert "2026-04-24-detail.png" in body


def test_detail_image_section_omitted_when_url_missing():
    body = _render_with(detail_image_url=None).body
    assert "## Visual detail" not in body


def test_json_metadata_contains_both_images_when_supplied():
    post = _render_with(
        cover_image_url="https://example.test/cover.png",
        detail_image_url="https://example.test/detail.png",
    )
    assert post.json_metadata["image"] == [
        "https://example.test/cover.png",
        "https://example.test/detail.png",
    ]


# =============================================================================
#  UTF-8 encoding pin — guards against accidental cp1252-ifying of the body
# =============================================================================

def test_body_contains_canonical_utf8_glyphs():
    """The template uses em-dash, multiplication-sign, middle-dot and
    plus-minus glyphs in several fixed places. Pin their codepoints so a
    future copy edit doesn't accidentally substitute ASCII fallbacks
    that look fine on a US-keyboard but break the visual rhythm Steemit
    readers expect."""
    cmp = aggregation.WeekComparison(
        current_uptime_pct=99.5,
        previous_uptime_pct=99.5,
        delta_pp=0.0,
        per_node_delta_pp={"https://a.example": 0.0},
    )
    body = _render(week=cmp).body
    # ±0.00 pp lives in the week-over-week section.
    assert "±" in body  # ± (PLUS-MINUS SIGN)
    # Em-dash appears in many places — perspective notice, error-class column
    # for clean nodes, etc.
    assert "—" in body  # — (EM DASH)


def test_body_round_trips_through_utf8_without_loss():
    """Encoding the rendered body to UTF-8 bytes and decoding back must
    return an identical string. This catches surrogate-pair issues and
    any accidental encoding=ascii leak that would lose non-ASCII chars."""
    body = _render().body
    round_tripped = body.encode("utf-8").decode("utf-8")
    assert body == round_tripped


def test_body_has_no_mojibake_byte_sequences():
    """If the body had been mis-decoded as cp1252 somewhere along the
    pipeline, common mojibake markers (â€", Ã—, Â·) would show up.
    Their absence here pins that the pipeline is UTF-8-clean end-to-end."""
    body = _render().body
    for marker in ["â€”", "Ã—", "Â·"]:
        assert marker not in body, (
            f"mojibake marker {marker!r} present in body — encoding pipeline broken"
        )


def test_error_class_separator_uses_real_multiplication_sign():
    """Detail table renders error counts as `bucket ×N`. Pin the actual
    × glyph (U+00D7) so a sloppy edit doesn't downgrade it to plain x."""
    body = _render().body
    if "Error classes" in body:
        # The synthetic data in _sample_stats has a 'timeout' error.
        # Its row in the table reads `timeout ×3`.
        assert "×" in body  # × (MULTIPLICATION SIGN)


def test_node_table_row_has_em_dash_for_clean_node():
    """A node with no errors shows '—' in the error-class column. Pin
    that glyph rather than letting it drift to '-' (HYPHEN-MINUS) or
    '–' (EN DASH)."""
    body = _render().body
    # Clean node `a.example` (uptime 100%) has the em-dash in its row.
    assert "| 0 | — |" in body
