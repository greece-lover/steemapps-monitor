"""Etappe 9 additions to aggregation: source_count tracking."""

from __future__ import annotations

from reporter import aggregation


def _row(*, ok: bool = True, source: str = "primary") -> dict:
    return {
        "timestamp": "2026-04-24T10:00:00Z",
        "success": 1 if ok else 0,
        "latency_ms": 200 if ok else None,
        "block_height": 1000 if ok else None,
        "error_message": None if ok else "timeout",
        "source_location": source,
    }


def test_source_count_is_one_with_single_source():
    rows = [_row(source="primary") for _ in range(5)]
    s = aggregation.aggregate_node(rows, url="https://x.example", region="eu")
    assert s.source_count == 1


def test_source_count_counts_distinct_sources():
    rows = [
        _row(source="primary"),
        _row(source="participant-us"),
        _row(source="participant-asia"),
        _row(source="primary"),
    ]
    s = aggregation.aggregate_node(rows, url="https://x.example", region="eu")
    assert s.source_count == 3


def test_source_count_falls_back_to_one_when_field_missing():
    """Old measurement rows that pre-date the source_location column should
    still aggregate cleanly with source_count=1 — never zero."""
    rows = [
        {"timestamp": "2026-04-24T10:00:00Z", "success": 1,
         "latency_ms": 200, "block_height": 1000, "error_message": None}
        for _ in range(3)
    ]
    s = aggregation.aggregate_node(rows, url="https://x.example", region="eu")
    assert s.source_count == 1


def test_custom_json_payload_includes_source_count():
    rows = [_row(source="primary"), _row(source="participant-us")]
    per_node = {"https://x.example": aggregation.aggregate_node(rows, url="https://x.example", region="eu")}
    gs = aggregation.aggregate_global(per_node, {"https://x.example": rows})
    payload = aggregation.to_custom_json_payload(
        day="2026-04-24",
        window_start="2026-04-24T00:00:00Z",
        window_end="2026-04-25T00:00:00Z",
        source_location="primary", methodology_version="mv1",
        per_node=per_node, global_stats=gs,
    )
    assert payload["nodes"][0]["source_count"] == 2
