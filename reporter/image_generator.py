"""Daily report cover image — generates a 1200×675 PNG with Pillow.

Visual identity matches the steemapps brand: dark gradient background,
lime accent (#b7e34a), Inter-style sans body, monospace for technical
values. The image is meant to sit at the very top of the Steem post so a
feed reader sees the headline numbers without expanding the body.

Layout (1200 × 675):
    ┌─────────────────────────────────────────────────────────────┐
    │ ▌ STEEM API HEALTH · Daily Report           2026-04-25      │
    ├─────────────────────────────────────────────────────────────┤
    │  FASTEST                     SLOWEST                        │
    │  ┌────┐ ┌────┐ ┌────┐        ┌────┐ ┌────┐ ┌────┐           │
    │  │... │ │... │ │... │        │... │ │... │ │... │           │
    │  └────┘ └────┘ └────┘        └────┘ └────┘ └────┘           │
    │                                                             │
    │           api.steemapps.com · @steem-api-health             │
    └─────────────────────────────────────────────────────────────┘

Pure stdlib + Pillow. No matplotlib, no numpy, no external converters,
so the dependency footprint stays tiny.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from reporter.aggregation import (
    CrossRegionResult,
    HourPattern,
    NodeStats,
)


# -----------------------------------------------------------------
#  Visual constants — pinned so the look stays in sync with the
#  dashboard's CSS.
# -----------------------------------------------------------------

WIDTH = 1200
HEIGHT = 675
PADDING = 40

# Background gradient stops (top → bottom).
BG_TOP = (10, 10, 10)        # #0a0a0a
BG_MID = (21, 24, 30)        # #15181e
BG_BOT = (26, 30, 38)        # #1a1e26

ACCENT = (183, 227, 74)      # #b7e34a
ACCENT_DIM = (76, 90, 32)    # #4c5a20

TEXT = (237, 237, 237)
TEXT_MUTED = (140, 140, 140)
TEXT_DIM = (94, 94, 94)

CARD_BG = (24, 24, 24)
CARD_BORDER = (38, 38, 38)
CARD_RADIUS = 8

# Dashed dividers — drawn as simple lines for now.
DIVIDER = (38, 38, 38)


# -----------------------------------------------------------------
#  Font discovery
# -----------------------------------------------------------------

# Tried in order; first existing path wins. Pinning an explicit list
# rather than scanning system fonts avoids picking something obscure
# that paints emoji glyphs as boxes.
_FONT_REGULAR_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arial.ttf",
]
_FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_FONT_MONO_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "C:/Windows/Fonts/consola.ttf",
]


def _first_existing(paths: list[str]) -> Optional[str]:
    for p in paths:
        if Path(p).exists():
            return p
    return None


def _load_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    path = _first_existing(candidates)
    if path is not None:
        return ImageFont.truetype(path, size)
    # Pillow ≥ 10 ships a TrueType DejaVu fallback inside the package
    # itself, so this still produces something readable.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# -----------------------------------------------------------------
#  Drawing helpers
# -----------------------------------------------------------------


def _interpolate(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def _draw_gradient(img: Image.Image) -> None:
    """Vertical 3-stop gradient: BG_TOP → BG_MID → BG_BOT.

    Drawing one horizontal line per Y row keeps the implementation
    trivially correct and runs in <50 ms for 675 rows."""
    draw = ImageDraw.Draw(img)
    half = HEIGHT // 2
    for y in range(HEIGHT):
        if y <= half:
            t = y / half if half else 0
            color = _interpolate(BG_TOP, BG_MID, t)
        else:
            t = (y - half) / (HEIGHT - half)
            color = _interpolate(BG_MID, BG_BOT, t)
        draw.line([(0, y), (WIDTH, y)], fill=color)


def _draw_grid_overlay(img: Image.Image) -> None:
    """Subtle 40-px grid overlaid on the gradient — same trick as the
    dashboard's CSS pattern, gives the image a faint technical texture."""
    draw = ImageDraw.Draw(img, "RGBA")
    for x in range(0, WIDTH, 40):
        draw.line([(x, 0), (x, HEIGHT)], fill=(183, 227, 74, 8), width=1)
    for y in range(0, HEIGHT, 40):
        draw.line([(0, y), (WIDTH, y)], fill=(183, 227, 74, 8), width=1)


def _short_url(url: str) -> str:
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


def _text_size(font: ImageFont.ImageFont, text: str) -> tuple[int, int]:
    """Wrapper around getbbox that returns (width, height) for any font."""
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


# -----------------------------------------------------------------
#  Card / tile rendering
# -----------------------------------------------------------------


TILE_W = 168
TILE_H = 130
TILE_GAP = 12


def _draw_tile(
    img: Image.Image,
    x: int,
    y: int,
    *,
    rank: int,
    url: str,
    latency_ms: Optional[int],
    uptime_pct: float,
    region: Optional[str],
    accent_text: bool,
    fonts: dict,
) -> None:
    """Render a single node tile at (x, y).

    `accent_text` flags the latency in lime when True (used for the
    'fastest' column) — for the 'slowest' column we use plain TEXT to
    avoid making the slow node look like a positive metric."""
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (x, y, x + TILE_W, y + TILE_H),
        radius=CARD_RADIUS,
        fill=CARD_BG,
        outline=CARD_BORDER,
        width=1,
    )

    # Rank badge in the top-left corner.
    draw.text(
        (x + 12, y + 8),
        f"#{rank}",
        font=fonts["mono_small"],
        fill=TEXT_DIM,
    )

    # Latency value, big and centred horizontally.
    latency_str = f"{latency_ms} ms" if latency_ms is not None else "—"
    lw, lh = _text_size(fonts["bold_xl"], latency_str)
    draw.text(
        (x + (TILE_W - lw) / 2, y + 28),
        latency_str,
        font=fonts["bold_xl"],
        fill=ACCENT if accent_text else TEXT,
    )

    # Uptime row.
    uptime_str = f"{uptime_pct:.2f}% uptime"
    uw, _ = _text_size(fonts["mono_small"], uptime_str)
    draw.text(
        (x + (TILE_W - uw) / 2, y + 70),
        uptime_str,
        font=fonts["mono_small"],
        fill=TEXT_MUTED,
    )

    # Node URL — truncate if too wide.
    short = _short_url(url)
    while _text_size(fonts["mono_small"], short)[0] > TILE_W - 16 and len(short) > 4:
        short = short[:-1]
    if short != _short_url(url):
        short = short[:-1] + "…"
    sw, _ = _text_size(fonts["mono_small"], short)
    draw.text(
        (x + (TILE_W - sw) / 2, y + 92),
        short,
        font=fonts["mono_small"],
        fill=TEXT,
    )

    # Region label, even smaller, at the bottom.
    if region:
        rw, _ = _text_size(fonts["mono_tiny"], region)
        draw.text(
            (x + (TILE_W - rw) / 2, y + 110),
            region,
            font=fonts["mono_tiny"],
            fill=TEXT_DIM,
        )


# -----------------------------------------------------------------
#  Public entry point
# -----------------------------------------------------------------


def render_daily_image(
    *,
    day: str,
    per_node: dict[str, NodeStats],
    output_path: Path,
) -> Path:
    """Render the cover image for `day` and write it to `output_path`.

    Returns the resolved output path. Idempotent — calling twice with
    the same day overwrites the file. The caller controls whether that
    file lands in /tmp (dry-run) or /var/www (production)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    _draw_gradient(img)
    _draw_grid_overlay(img)

    fonts = {
        "title":     _load_font(_FONT_BOLD_CANDIDATES, 30),
        "date":      _load_font(_FONT_MONO_CANDIDATES, 38),
        "section":   _load_font(_FONT_BOLD_CANDIDATES, 16),
        "footer":    _load_font(_FONT_REGULAR_CANDIDATES, 18),
        "bold_xl":   _load_font(_FONT_BOLD_CANDIDATES, 28),
        "mono_small": _load_font(_FONT_MONO_CANDIDATES, 13),
        "mono_tiny":  _load_font(_FONT_MONO_CANDIDATES, 11),
    }

    draw = ImageDraw.Draw(img)

    # ----- Header -----
    # Lime brand bar on the left edge of the header strip.
    draw.rectangle((PADDING, PADDING, PADDING + 6, PADDING + 56), fill=ACCENT)

    draw.text(
        (PADDING + 22, PADDING + 4),
        "STEEM API HEALTH",
        font=fonts["title"],
        fill=TEXT,
    )
    draw.text(
        (PADDING + 22, PADDING + 38),
        "Daily Report",
        font=fonts["section"],
        fill=TEXT_MUTED,
    )

    # Date in the top-right corner — large and monospace so it doubles
    # as the document anchor.
    dw, _ = _text_size(fonts["date"], day)
    draw.text(
        (WIDTH - PADDING - dw, PADDING + 8),
        day,
        font=fonts["date"],
        fill=ACCENT,
    )

    # Divider under the header.
    div_y = PADDING + 80
    draw.line([(PADDING, div_y), (WIDTH - PADDING, div_y)], fill=DIVIDER, width=1)

    # ----- Body: Fastest / Slowest columns -----

    # Drop nodes without an average latency (no successful tick).
    measurable = [
        (url, s) for url, s in per_node.items()
        if s.latency.avg_ms is not None
    ]
    by_avg = sorted(measurable, key=lambda kv: kv[1].latency.avg_ms)
    fastest = by_avg[:3]
    slowest = list(reversed(by_avg[-3:])) if len(by_avg) >= 3 else by_avg[::-1]

    section_y = div_y + 30

    # Column anchors — left column starts at PADDING, right column at
    # WIDTH/2 + 20. Each column hosts one section title plus three tiles.
    col_left_x = PADDING
    col_right_x = WIDTH // 2 + 20

    draw.text((col_left_x, section_y), "FASTEST", font=fonts["section"], fill=ACCENT)
    draw.text((col_right_x, section_y), "SLOWEST", font=fonts["section"], fill=TEXT_MUTED)

    tiles_y = section_y + 32

    for i, (url, s) in enumerate(fastest):
        x = col_left_x + i * (TILE_W + TILE_GAP)
        _draw_tile(
            img, x, tiles_y,
            rank=i + 1, url=url,
            latency_ms=s.latency.avg_ms,
            uptime_pct=s.uptime_pct,
            region=s.region,
            accent_text=True,
            fonts=fonts,
        )

    for i, (url, s) in enumerate(slowest):
        x = col_right_x + i * (TILE_W + TILE_GAP)
        _draw_tile(
            img, x, tiles_y,
            rank=i + 1, url=url,
            latency_ms=s.latency.avg_ms,
            uptime_pct=s.uptime_pct,
            region=s.region,
            accent_text=False,
            fonts=fonts,
        )

    # Below the tiles: total measurements + node count.
    summary_y = tiles_y + TILE_H + 26
    total_measurements = sum(s.total for s in per_node.values())
    total_ok = sum(s.ok for s in per_node.values())
    summary_text = (
        f"{len(per_node)} nodes tracked  ·  "
        f"{total_measurements:,} measurements  ·  "
        f"{(100.0 * total_ok / total_measurements if total_measurements else 0):.2f}% uptime"
    )
    sw, _ = _text_size(fonts["footer"], summary_text)
    draw.text(
        ((WIDTH - sw) / 2, summary_y),
        summary_text,
        font=fonts["footer"],
        fill=TEXT_MUTED,
    )

    # ----- Footer -----
    footer_text = "api.steemapps.com  ·  @steem-api-health"
    fw, _ = _text_size(fonts["footer"], footer_text)
    draw.text(
        ((WIDTH - fw) / 2, HEIGHT - PADDING - 28),
        footer_text,
        font=fonts["footer"],
        fill=TEXT_DIM,
    )

    img.save(output_path, format="PNG", optimize=True)
    return output_path


# =============================================================================
#  Phase 6 Etappe 12a — second image: detail charts (1200 × 900)
# =============================================================================
#
# Layout:
#     ┌────────────────────────────────────────────────────────────────────┐
#     │ ▌ STEEM API HEALTH · Detail · 2026-04-25                           │
#     ├────────────────────────────────────────────────────────────────────┤
#     │                                                                    │
#     │  LATENCY: AVG vs P99 PER NODE  (horizontal bars)                   │
#     │                                                                    │
#     ├────────────────────────────────────────────────────────────────────┤
#     │                                                                    │
#     │  HOURLY PERFORMANCE  (24-bar bottom-anchored chart)                │
#     │                                                                    │
#     ├────────────────────────────────────────────────────────────────────┤
#     │                                                                    │
#     │  CROSS-REGION COMPARISON  (vertical bars per node × region)        │
#     │  — replaced by an info line if no multi-region data is available   │
#     │                                                                    │
#     └────────────────────────────────────────────────────────────────────┘
#
# Pure Pillow — same drawing primitives as the cover image, no matplotlib
# dependency. The three stripes share a fixed-height layout so the file
# size and rendering time stay predictable across different data shapes.


DETAIL_WIDTH = 1200
DETAIL_HEIGHT = 900

_HEADER_H = 90
_STRIPE_GAP = 20
_STRIPE_PADDING = 24
_STRIPE_TITLE_H = 28


def _draw_detail_gradient(img: Image.Image) -> None:
    """Same 3-stop gradient as the cover, scaled to the taller canvas."""
    draw = ImageDraw.Draw(img)
    half = DETAIL_HEIGHT // 2
    for y in range(DETAIL_HEIGHT):
        if y <= half:
            t = y / half if half else 0
            color = _interpolate(BG_TOP, BG_MID, t)
        else:
            t = (y - half) / (DETAIL_HEIGHT - half)
            color = _interpolate(BG_MID, BG_BOT, t)
        draw.line([(0, y), (DETAIL_WIDTH, y)], fill=color)


def _draw_detail_grid(img: Image.Image) -> None:
    draw = ImageDraw.Draw(img, "RGBA")
    for x in range(0, DETAIL_WIDTH, 40):
        draw.line([(x, 0), (x, DETAIL_HEIGHT)], fill=(183, 227, 74, 8), width=1)
    for y in range(0, DETAIL_HEIGHT, 40):
        draw.line([(0, y), (DETAIL_WIDTH, y)], fill=(183, 227, 74, 8), width=1)


def _draw_detail_header(img: Image.Image, day: str, fonts: dict) -> None:
    """Brand bar + title left, day badge right. Mirrors the cover image
    so the two PNGs read as a pair."""
    draw = ImageDraw.Draw(img)
    draw.rectangle((PADDING, PADDING, PADDING + 6, PADDING + 56), fill=ACCENT)
    draw.text((PADDING + 22, PADDING + 4), "STEEM API HEALTH",
              font=fonts["title"], fill=TEXT)
    draw.text((PADDING + 22, PADDING + 38), "Detail charts",
              font=fonts["section"], fill=TEXT_MUTED)
    dw, _ = _text_size(fonts["date"], day)
    draw.text((DETAIL_WIDTH - PADDING - dw, PADDING + 8), day,
              font=fonts["date"], fill=ACCENT)
    div_y = PADDING + 80
    draw.line([(PADDING, div_y), (DETAIL_WIDTH - PADDING, div_y)], fill=DIVIDER, width=1)


def _stripe_box(stripe_index: int) -> tuple[int, int, int, int]:
    """Bounding box (x0, y0, x1, y1) for the Nth content stripe.

    Three stripes evenly distributed below the header. Maths intentionally
    in one place so a future fourth stripe (or layout tweak) doesn't drift
    the chart positions out of sync."""
    body_top = _HEADER_H + PADDING
    body_bottom = DETAIL_HEIGHT - PADDING - 24       # leave room for footer line
    available = body_bottom - body_top
    stripe_h = (available - 2 * _STRIPE_GAP) // 3
    y0 = body_top + stripe_index * (stripe_h + _STRIPE_GAP)
    return (PADDING, y0, DETAIL_WIDTH - PADDING, y0 + stripe_h)


def _draw_stripe_card(
    img: Image.Image, box: tuple[int, int, int, int], title: str, fonts: dict,
) -> tuple[int, int, int, int]:
    """Draw a card background and a title bar. Returns the inner content
    box that subsequent chart-drawing helpers can paint into."""
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    draw.rounded_rectangle((x0, y0, x1, y1), radius=CARD_RADIUS,
                           fill=CARD_BG, outline=CARD_BORDER, width=1)
    draw.text((x0 + _STRIPE_PADDING, y0 + 12), title,
              font=fonts["section"], fill=ACCENT)
    return (
        x0 + _STRIPE_PADDING,
        y0 + 12 + _STRIPE_TITLE_H,
        x1 - _STRIPE_PADDING,
        y1 - _STRIPE_PADDING // 2,
    )


def _draw_centred_message(img: Image.Image, box: tuple[int, int, int, int],
                          message: str, fonts: dict) -> None:
    """For empty-data stripes: show one muted line centred in the card."""
    draw = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    mw, mh = _text_size(fonts["footer"], message)
    draw.text((x0 + (x1 - x0 - mw) // 2, y0 + (y1 - y0 - mh) // 2),
              message, font=fonts["footer"], fill=TEXT_DIM)


# ----- Stripe 1: latency per node (avg + p99 horizontal bars) -----

def _draw_latency_stripe(
    img: Image.Image, content_box: tuple[int, int, int, int],
    per_node: dict[str, NodeStats], fonts: dict,
) -> None:
    """One row per node: label on the left, bar showing avg latency,
    a fainter overlay showing p99. Same scale across all rows so visual
    comparison is meaningful."""
    measurable = [(url, s) for url, s in per_node.items() if s.latency.avg_ms is not None]
    if not measurable:
        _draw_centred_message(img, content_box,
                              "No successful measurements in the window.", fonts)
        return
    # Sort fastest first so the eye runs top-to-bottom from good to bad.
    measurable.sort(key=lambda kv: kv[1].latency.avg_ms)
    draw = ImageDraw.Draw(img)
    cx0, cy0, cx1, cy1 = content_box
    # Label column width is fixed so bars line up between rows.
    label_w = 200
    bar_x0 = cx0 + label_w + 12
    bar_x1 = cx1 - 80                              # leave room for value text on the right
    # Scale: max p99 across the fleet sets the right edge.
    scale_max = max(
        (s.latency.p99_ms or s.latency.avg_ms or 0) for _, s in measurable
    )
    scale_max = max(scale_max, 1)
    n = len(measurable)
    row_h = max(18, (cy1 - cy0) // max(n, 1))
    for i, (url, s) in enumerate(measurable):
        y = cy0 + i * row_h + 2
        # Label.
        label = _short_url(url)
        # Truncate to fit.
        while _text_size(fonts["mono_small"], label)[0] > label_w - 8 and len(label) > 4:
            label = label[:-1]
        if label != _short_url(url):
            label = label[:-1] + "…"
        draw.text((cx0, y + (row_h - 14) // 2), label,
                  font=fonts["mono_small"], fill=TEXT)
        # p99 bar (fainter, behind avg).
        if s.latency.p99_ms is not None:
            p99_w = int((bar_x1 - bar_x0) * (s.latency.p99_ms / scale_max))
            draw.rectangle(
                (bar_x0, y + 4, bar_x0 + p99_w, y + row_h - 6),
                fill=ACCENT_DIM,
            )
        # avg bar (foreground, lime accent).
        avg_w = int((bar_x1 - bar_x0) * (s.latency.avg_ms / scale_max))
        draw.rectangle(
            (bar_x0, y + 6, bar_x0 + avg_w, y + row_h - 8),
            fill=ACCENT,
        )
        # Value text.
        value = f"{s.latency.avg_ms} ms"
        if s.latency.p99_ms is not None:
            value += f"  · p99 {s.latency.p99_ms}"
        draw.text((bar_x1 + 6, y + (row_h - 14) // 2), value,
                  font=fonts["mono_small"], fill=TEXT_MUTED)


# ----- Stripe 2: hourly performance (bottom-anchored bars) -----

def _draw_hour_stripe(
    img: Image.Image, content_box: tuple[int, int, int, int],
    pattern: HourPattern, fonts: dict,
) -> None:
    """24 bars, one per UTC hour. Empty hours are drawn as a thin tick
    on the baseline so the missing data is visible, not hidden.

    Best/worst hours are highlighted: best in lime, worst in down-red.
    """
    populated = [b for b in pattern.buckets if b.avg_latency_ms is not None]
    if not populated:
        _draw_centred_message(img, content_box,
                              "Not enough hourly data yet.", fonts)
        return
    draw = ImageDraw.Draw(img)
    cx0, cy0, cx1, cy1 = content_box
    # Reserve a small label strip below for hour labels (00, 06, 12, 18).
    label_strip = 16
    chart_top = cy0 + 6
    chart_bottom = cy1 - label_strip
    chart_h = chart_bottom - chart_top
    bar_w = max(8, (cx1 - cx0) // 28)              # 24 bars + gaps
    gap = max(2, ((cx1 - cx0) - bar_w * 24) // 23)
    # Scale: max avg sets the top.
    scale_max = max(b.avg_latency_ms for b in populated)
    scale_max = max(scale_max, 1)
    best_h = pattern.best.hour_utc if pattern.best else None
    worst_h = pattern.worst.hour_utc if pattern.worst else None

    # Down/ok colours from monitor's status palette.
    BAR_OK = ACCENT
    BAR_BEST = (94, 234, 136)                      # status-ok green
    BAR_WORST = (239, 106, 106)                    # status-down red

    for i, bucket in enumerate(pattern.buckets):
        bx = cx0 + i * (bar_w + gap)
        if bucket.avg_latency_ms is None:
            # 2-px tick on the baseline marks the gap.
            draw.line([(bx, chart_bottom - 2), (bx + bar_w, chart_bottom - 2)],
                      fill=TEXT_DIM, width=2)
            continue
        h = int(chart_h * (bucket.avg_latency_ms / scale_max))
        h = max(2, h)
        colour = BAR_OK
        if bucket.hour_utc == best_h:
            colour = BAR_BEST
        elif bucket.hour_utc == worst_h:
            colour = BAR_WORST
        draw.rectangle((bx, chart_bottom - h, bx + bar_w, chart_bottom), fill=colour)
        # Hour label every 6 hours so the strip stays readable.
        if bucket.hour_utc % 6 == 0:
            label = f"{bucket.hour_utc:02d}"
            lw, _ = _text_size(fonts["mono_tiny"], label)
            draw.text((bx + (bar_w - lw) // 2, chart_bottom + 2), label,
                      font=fonts["mono_tiny"], fill=TEXT_DIM)
    # Best/worst legend.
    if pattern.best and pattern.worst:
        legend = (
            f"best {pattern.best.hour_utc:02d}h · {pattern.best.avg_latency_ms} ms     "
            f"worst {pattern.worst.hour_utc:02d}h · {pattern.worst.avg_latency_ms} ms"
        )
        lw, _ = _text_size(fonts["mono_small"], legend)
        draw.text((cx1 - lw, chart_top - 4), legend,
                  font=fonts["mono_small"], fill=TEXT_MUTED)


# ----- Stripe 3: cross-region comparison -----

def _draw_cross_region_stripe(
    img: Image.Image, content_box: tuple[int, int, int, int],
    cr: Optional[CrossRegionResult], fonts: dict,
) -> None:
    """Vertical bar group per node: one bar per source region.
    When no multi-region data is available the stripe shows a single
    info line — the section is still drawn so the layout grid stays
    constant across daily runs."""
    if cr is None or not cr.entries:
        _draw_centred_message(
            img, content_box,
            "Multi-region data not yet available — invite contributors at "
            "api.steemapps.com/join.html",
            fonts,
        )
        return
    draw = ImageDraw.Draw(img)
    cx0, cy0, cx1, cy1 = content_box
    # Top up to 8 most-variant nodes. With 10 nodes total in nodes.json
    # this is effectively "all of them" today; the cap keeps the stripe
    # readable if a future config doubles the fleet.
    entries = cr.entries[:8]
    n_groups = len(entries)
    # Each group has up to 4 region bars. Calculate a layout that fits.
    chart_top = cy0 + 6
    chart_bottom = cy1 - 18                        # reserve label strip
    chart_h = chart_bottom - chart_top
    group_w = max(80, (cx1 - cx0 - 20) // max(n_groups, 1))
    # Scale across every region average we render.
    all_vals = [v for e in entries for v in e.by_region.values()]
    scale_max = max(all_vals) if all_vals else 1

    # Reserve 4 region "swatches" used as legend keys.
    REGION_PALETTE = [ACCENT, (91, 155, 255), (196, 139, 255), (245, 164, 98)]
    # Keep stable region→colour mapping across the stripe so the eye can
    # follow "asia" or "eu-central" between groups.
    region_colours: dict[str, tuple[int, int, int]] = {}
    def _colour_for(region: str) -> tuple[int, int, int]:
        if region not in region_colours:
            region_colours[region] = REGION_PALETTE[len(region_colours) % len(REGION_PALETTE)]
        return region_colours[region]

    for gi, e in enumerate(entries):
        gx0 = cx0 + gi * group_w + 4
        regions_sorted = sorted(e.by_region.items(), key=lambda kv: kv[0])
        nbars = len(regions_sorted)
        bar_w = max(6, (group_w - 24) // max(nbars, 1))
        for bi, (region, ms) in enumerate(regions_sorted):
            bx = gx0 + bi * bar_w
            h = max(2, int(chart_h * (ms / scale_max)))
            draw.rectangle((bx, chart_bottom - h, bx + bar_w - 2, chart_bottom),
                           fill=_colour_for(region))
        # Node label.
        node_short = _short_url(e.node_url)
        while _text_size(fonts["mono_tiny"], node_short)[0] > group_w - 8 and len(node_short) > 4:
            node_short = node_short[:-1]
        if node_short != _short_url(e.node_url):
            node_short = node_short[:-1] + "…"
        nw, _ = _text_size(fonts["mono_tiny"], node_short)
        draw.text((gx0 + (group_w - nw) // 2, chart_bottom + 2), node_short,
                  font=fonts["mono_tiny"], fill=TEXT_DIM)

    # Legend top-right.
    legend_x = cx1
    for region, colour in region_colours.items():
        label = region
        lw, _ = _text_size(fonts["mono_small"], label)
        legend_x -= lw + 28
        draw.rectangle((legend_x, chart_top - 2, legend_x + 12, chart_top + 10),
                       fill=colour)
        draw.text((legend_x + 16, chart_top - 4), label,
                  font=fonts["mono_small"], fill=TEXT_MUTED)


# ----- Public entry point -----

def render_detail_image(
    *,
    day: str,
    per_node: dict[str, NodeStats],
    hour_pattern: HourPattern,
    cross_region: Optional[CrossRegionResult],
    output_path: Path,
) -> Path:
    """Render the second daily PNG (1200×900) and write it to `output_path`.

    Three stripes top-to-bottom: latency per node (avg + p99 bars),
    hourly performance (24-hour bottom-anchored bars), cross-region
    comparison (vertical bars per node × region, info line when no
    multi-region data is available).

    Returns the resolved output path. Idempotent on the same `day`."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (DETAIL_WIDTH, DETAIL_HEIGHT), BG_TOP)
    _draw_detail_gradient(img)
    _draw_detail_grid(img)

    fonts = {
        "title":     _load_font(_FONT_BOLD_CANDIDATES, 30),
        "date":      _load_font(_FONT_MONO_CANDIDATES, 38),
        "section":   _load_font(_FONT_BOLD_CANDIDATES, 16),
        "footer":    _load_font(_FONT_REGULAR_CANDIDATES, 18),
        "bold_xl":   _load_font(_FONT_BOLD_CANDIDATES, 28),
        "mono_small": _load_font(_FONT_MONO_CANDIDATES, 13),
        "mono_tiny":  _load_font(_FONT_MONO_CANDIDATES, 11),
    }

    _draw_detail_header(img, day, fonts)

    # Stripe 0 — latency per node.
    box0 = _stripe_box(0)
    inner0 = _draw_stripe_card(img, box0,
                               "LATENCY PER NODE  ·  AVG + P99",
                               fonts)
    _draw_latency_stripe(img, inner0, per_node, fonts)

    # Stripe 1 — hourly performance.
    box1 = _stripe_box(1)
    inner1 = _draw_stripe_card(img, box1,
                               "HOURLY PERFORMANCE  ·  24 H UTC",
                               fonts)
    _draw_hour_stripe(img, inner1, hour_pattern, fonts)

    # Stripe 2 — cross-region.
    box2 = _stripe_box(2)
    inner2 = _draw_stripe_card(img, box2,
                               "CROSS-REGION COMPARISON",
                               fonts)
    _draw_cross_region_stripe(img, inner2, cross_region, fonts)

    # Footer — same anchor as the cover.
    draw = ImageDraw.Draw(img)
    footer_text = "api.steemapps.com  ·  @steem-api-health"
    fw, _ = _text_size(fonts["footer"], footer_text)
    draw.text(((DETAIL_WIDTH - fw) / 2, DETAIL_HEIGHT - PADDING - 28),
              footer_text, font=fonts["footer"], fill=TEXT_DIM)

    img.save(output_path, format="PNG", optimize=True)
    return output_path
