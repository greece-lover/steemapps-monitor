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

from reporter.aggregation import NodeStats


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
