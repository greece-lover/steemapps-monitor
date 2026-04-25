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
        latency=LatencyStats(avg_ms=avg, min_ms=avg, max_ms=avg, p95_ms=avg),
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
