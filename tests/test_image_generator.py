"""Image generator tests — verifies a PNG of the right shape lands at
the requested path. We don't pixel-compare (font fallback differs across
platforms) but we do check the file exists, opens as a PNG, and matches
the spec'd 1200×675 dimensions."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from reporter import image_generator
from reporter.aggregation import LatencyStats, NodeStats


def _stats(url: str, avg: int | None, uptime: float = 100.0) -> NodeStats:
    return NodeStats(
        url=url, region="eu", total=100,
        ok=int(100 * uptime / 100), uptime_pct=uptime,
        errors=0,
        latency=LatencyStats(avg_ms=avg, min_ms=avg, max_ms=avg,
                             p50_ms=avg, p95_ms=avg, p99_ms=avg),
    )


def test_render_daily_image_writes_png_with_correct_dimensions(tmp_path: Path):
    per_node = {
        f"https://n{i}.example": _stats(f"https://n{i}.example", avg=100 + i * 50)
        for i in range(6)
    }
    out = tmp_path / "2026-04-24.png"
    written = image_generator.render_daily_image(
        day="2026-04-24", per_node=per_node, output_path=out,
    )
    assert written == out
    assert out.exists()
    with Image.open(out) as im:
        assert im.size == (image_generator.WIDTH, image_generator.HEIGHT)
        assert im.format == "PNG"


def test_render_daily_image_handles_unmeasurable_nodes(tmp_path: Path):
    """Nodes without an average latency (no successful tick) are dropped from
    the tile rows but must not crash the generator."""
    per_node = {
        "https://measurable.example": _stats("https://measurable.example", avg=200),
        "https://dead.example":       _stats("https://dead.example", avg=None, uptime=0.0),
    }
    out = tmp_path / "2026-04-24.png"
    image_generator.render_daily_image(
        day="2026-04-24", per_node=per_node, output_path=out,
    )
    assert out.exists()


def test_render_daily_image_creates_parent_dir(tmp_path: Path):
    out = tmp_path / "deep" / "nested" / "2026-04-24.png"
    image_generator.render_daily_image(
        day="2026-04-24",
        per_node={"https://a.example": _stats("https://a.example", avg=100)},
        output_path=out,
    )
    assert out.exists()


# =============================================================================
#  Etappe 12a — render_detail_image (1200 × 900)
# =============================================================================

from reporter.aggregation import (
    CrossRegionEntry,
    CrossRegionResult,
    HourBucket,
    HourPattern,
)


def _hour_pattern(populated: dict[int, int] | None = None) -> HourPattern:
    """Build a HourPattern with avg latencies for the listed hours, the
    rest empty."""
    populated = populated or {}
    buckets = []
    for h in range(24):
        if h in populated:
            buckets.append(HourBucket(h, populated[h], 60))
        else:
            buckets.append(HourBucket(h, None, 0))
    pop = [b for b in buckets if b.avg_latency_ms is not None]
    best = min(pop, key=lambda b: b.avg_latency_ms) if pop else None
    worst = max(pop, key=lambda b: b.avg_latency_ms) if pop else None
    return HourPattern(buckets=buckets, best=best, worst=worst)


def test_render_detail_image_writes_png_with_correct_dimensions(tmp_path: Path):
    per_node = {
        f"https://n{i}.example": _stats(f"https://n{i}.example", avg=100 + i * 60)
        for i in range(6)
    }
    out = tmp_path / "2026-04-25-detail.png"
    written = image_generator.render_detail_image(
        day="2026-04-25", per_node=per_node,
        hour_pattern=_hour_pattern({h: 200 + h * 5 for h in range(0, 24, 2)}),
        cross_region=None,
        output_path=out,
    )
    assert written == out
    assert out.exists()
    with Image.open(out) as im:
        assert im.size == (image_generator.DETAIL_WIDTH, image_generator.DETAIL_HEIGHT)
        assert im.format == "PNG"


def test_render_detail_image_handles_empty_pattern(tmp_path: Path):
    """Fresh-monitor case — no successful ticks anywhere. Stripe 1+2 fall
    back to centred info messages, the file still writes cleanly."""
    out = tmp_path / "empty.png"
    image_generator.render_detail_image(
        day="2026-04-25",
        per_node={"https://dead.example": _stats("https://dead.example", avg=None, uptime=0.0)},
        hour_pattern=_hour_pattern({}),
        cross_region=None,
        output_path=out,
    )
    assert out.exists()


def test_render_detail_image_renders_cross_region_stripe(tmp_path: Path):
    """When cross-region data is supplied, stripe 3 draws bar groups.
    We can't pixel-compare but we can confirm the file writes and
    the dimensions are correct under that code path."""
    cr = CrossRegionResult(entries=[
        CrossRegionEntry("https://a.example", {"eu-central": 200, "asia": 450}, 2.25),
        CrossRegionEntry("https://b.example", {"eu-central": 150, "asia": 200}, 1.33),
    ])
    out = tmp_path / "cr.png"
    image_generator.render_detail_image(
        day="2026-04-25",
        per_node={
            "https://a.example": _stats("https://a.example", avg=325),
            "https://b.example": _stats("https://b.example", avg=175),
        },
        hour_pattern=_hour_pattern({h: 200 for h in range(24)}),
        cross_region=cr,
        output_path=out,
    )
    assert out.exists()
    with Image.open(out) as im:
        assert im.size == (image_generator.DETAIL_WIDTH, image_generator.DETAIL_HEIGHT)


def test_render_detail_image_creates_parent_dir(tmp_path: Path):
    out = tmp_path / "deep" / "detail.png"
    image_generator.render_detail_image(
        day="2026-04-25",
        per_node={"https://a.example": _stats("https://a.example", avg=100)},
        hour_pattern=_hour_pattern({10: 100}),
        cross_region=None,
        output_path=out,
    )
    assert out.exists()
