"""Template-rendering tests.

We don't pin the entire rendered body byte-for-byte — a word-level edit
to the copy shouldn't fail the suite. Instead, the tests check invariants
the template must maintain: both languages present, headers in the right
order, node rows present for every input node, footer verbatim, chain
reference rendered only when supplied.
"""

from __future__ import annotations

from reporter import aggregation, template


def _row(ts: str, ok: bool = True, latency: int | None = 200,
         height: int | None = 1000, err: str | None = None) -> dict:
    return {
        "timestamp": ts,
        "success": 1 if ok else 0,
        "latency_ms": latency,
        "block_height": height,
        "error_message": err,
    }


def _sample_stats():
    rows_by_node = {
        "https://a.example": [_row(f"2026-04-24T10:{i:02d}:00Z") for i in range(10)],
        "https://b.example": [
            _row(f"2026-04-24T10:{i:02d}:00Z", ok=(i < 7), latency=150 if i < 7 else None,
                 height=1000 if i < 7 else None, err=None if i < 7 else "timeout")
            for i in range(10)
        ],
    }
    per_node = {
        url: aggregation.aggregate_node(rs, url=url, region="eu")
        for url, rs in rows_by_node.items()
    }
    gs = aggregation.aggregate_global(per_node, rows_by_node)
    return per_node, gs


def _render(chain_reference=None, week=None):
    per_node, gs = _sample_stats()
    return template.render(
        day="2026-04-24",
        window_start="2026-04-24T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        per_node=per_node,
        global_stats=gs,
        week=week,
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
        chain_reference=chain_reference,
    )


def test_render_title_and_permlink():
    post = _render()
    assert post.title == "Steem API Monitor — Daily Report 2026-04-24"
    assert post.permlink == "steemapps-api-daily-report-2026-04-24"


def test_body_has_both_language_sections():
    post = _render()
    body = post.body
    assert "## English" in body
    assert "## Deutsch" in body
    # English before Deutsch in the body — keeps the top of the post
    # consistent for feed readers that truncate previews.
    assert body.index("## English") < body.index("## Deutsch")


def test_body_mentions_every_node():
    post = _render()
    # Nodes appear stripped of the `https://` prefix in the compact table.
    assert "a.example" in post.body
    assert "b.example" in post.body


def test_footer_contains_verbatim_english_and_german_blocks():
    post = _render()
    # Key lines from the Phase-5 brief — these are legally mandated copy
    # (the witness ask), so a test locks the exact wording.
    assert "maintained by @greece-lover" in post.body
    assert "betrieben von @greece-lover" in post.body
    assert "If you find this work valuable, consider voting for @greece-lover" in post.body
    assert "Wer die Arbeit unterstützen möchte" in post.body


def test_chain_reference_rendered_when_supplied():
    ref = template.ChainReference(tx_hash="abc123", block_num=12345)
    post = _render(chain_reference=ref)
    assert "abc123" in post.body
    assert "12345" in post.body


def test_chain_reference_fallback_when_absent():
    post = _render(chain_reference=None)
    # The "broadcast log" phrasing marks the fallback — the test accepts
    # either the English or German variant to avoid locking word choice.
    assert ("broadcast log" in post.body) or ("Broadcast-Log" in post.body)


def test_week_comparison_section_handles_none_gracefully():
    post = _render(week=None)
    # No crash, and a "no prior week" note is visible in both languages.
    assert "no prior week available" in post.body
    assert "noch keine Vorwoche verfügbar" in post.body


def test_week_comparison_renders_delta_line():
    cmp = aggregation.WeekComparison(
        current_uptime_pct=99.5,
        previous_uptime_pct=99.0,
        delta_pp=0.5,
        per_node_delta_pp={"https://a.example": 0.2, "https://b.example": 0.8},
    )
    post = _render(week=cmp)
    assert "99.50 %" in post.body
    assert "99.00 %" in post.body
    assert "+0.50 pp" in post.body


def test_json_metadata_contains_custom_json_id_and_tags():
    post = _render()
    assert post.json_metadata["tags"] == ["steem", "api", "monitoring"]
    assert post.json_metadata["format"] == "markdown"
    assert post.json_metadata["steemapps_monitor"]["custom_json_id"] == "steemapps_api_stats_daily"
    assert post.json_metadata["steemapps_monitor"]["day"] == "2026-04-24"
