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
