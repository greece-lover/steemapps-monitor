"""End-to-end dry run of the daily-report generator against synthetic
data. Writes everything to a tmp directory so the production DB and the
operator's local working DB stay untouched.

Usage:
    .venv/bin/python scripts/dry_run_daily_report.py
"""

from __future__ import annotations

import os
import sys
import tempfile

# Windows consoles default to cp1252 and would crash on Unicode
# arrows (↑↓·) in the body. Force UTF-8 so the script is portable.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass
from datetime import date, timedelta
from pathlib import Path

# Add repo root to sys.path so `import config` resolves to the monitor
# config (the same way the systemd unit's working directory does).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reporter import daily_report

# Use a tmp DB so this never touches the local working data file.
TMP_DIR = Path(tempfile.mkdtemp(prefix="steemapps-dryrun-report-"))
TMP_DB = TMP_DIR / "demo.sqlite"
IMAGE_DIR = TMP_DIR / "reports"

os.environ["STEEMAPPS_REPORTER_DB_PATH"] = str(TMP_DB)
os.environ["STEEMAPPS_REPORTER_IMAGE_DIR"] = str(IMAGE_DIR)
# Force dev mode and make the cover image URL public-looking so the test
# reflects what the production post would actually emit.
os.environ["STEEMAPPS_REPORTER_MODE"] = "dev"
os.environ["STEEMAPPS_REPORTER_IMAGE_URL_BASE"] = "https://api.steemapps.com/reports"

import config as monitor_config  # noqa: E402  (after env override)
import database  # noqa: E402

# Override the DB_PATH the seed function reads as well.
monitor_config.DB_PATH = TMP_DB


def main() -> int:
    print(f"== tmp dir: {TMP_DIR}")
    print(f"== seeding 14 days of synthetic data into {TMP_DB}")
    daily_report._seed_synthetic(TMP_DB)

    # Also adjust the image_url_base to the public path so the markdown
    # body shows what the live post will actually emit, not a tmp file://.
    # The dev-mode override in run() blanks image_url_base — so we patch
    # the loaded config back to the URL after the fact via env (the
    # underlying load() reads it).
    print(f"\n== running the report for yesterday with --dry-run")
    print("   (image_url_base IS preserved in this script so the body shows the")
    print("    public URL the production post would emit)\n")

    # We bypass the CLI dispatcher so we can keep image_url_base intact
    # even though `_force_dev` would otherwise blank it.
    from dataclasses import replace
    from reporter.config import load, MODE_DEV

    yesterday = date.today() - timedelta(days=1)
    cfg = load()
    cfg = replace(cfg, mode=MODE_DEV, image_dir=IMAGE_DIR)
    # Keep image_url_base so the dry-run output shows the production URL.

    # Re-implement run() inline with our patched cfg, since _force_dev
    # in the production code blanks the URL by design.
    import logger as logger_mod
    from datetime import timedelta as _td
    from reporter import aggregation, broadcast, image_generator, observations, query, template

    logger_mod.setup()
    day_str = yesterday.isoformat()
    start_iso, end_iso = query.utc_day_window(yesterday)
    rows = query.fetch_measurements_in_window(cfg.db_path, start_iso, end_iso)
    print(f"   fetched {len(rows)} rows for {day_str}")
    if not rows:
        print("   no data — aborting")
        return 2
    rows_by_node = query.group_by_node(rows)
    nodes_map = {n["url"]: n.get("region") for n in monitor_config.load_nodes()}
    per_node = {
        url: aggregation.aggregate_node(rs, url=url, region=nodes_map.get(url))
        for url, rs in rows_by_node.items()
    }
    global_stats = aggregation.aggregate_global(per_node, rows_by_node)

    image_path = cfg.image_dir / f"{day_str}.png"
    image_generator.render_daily_image(day=day_str, per_node=per_node, output_path=image_path)
    cover_url = f"{cfg.image_url_base}/{day_str}.png" if cfg.image_url_base else None

    yesterday_per_node = daily_report._build_per_node(cfg, yesterday - _td(days=1), nodes_map) or None
    week_history = daily_report._build_week_history(cfg, yesterday, nodes_map)
    obs_list = observations.gather_observations(
        per_node, global_stats,
        yesterday_per_node=yesterday_per_node, week_history=week_history,
    )

    cur_start, _ = query.utc_day_window(yesterday - _td(days=6))
    _, cur_end = query.utc_day_window(yesterday)
    prev_start, _ = query.utc_day_window(yesterday - _td(days=13))
    _, prev_end = query.utc_day_window(yesterday - _td(days=7))
    week = aggregation.compare_weeks(
        query.group_by_node(query.fetch_measurements_in_window(cfg.db_path, cur_start, cur_end)),
        query.group_by_node(query.fetch_measurements_in_window(cfg.db_path, prev_start, prev_end)),
    )

    post = template.render(
        day=day_str, window_start=start_iso, window_end=end_iso,
        per_node=per_node, global_stats=global_stats, week=week,
        observations=obs_list,
        source_location=monitor_config.SOURCE_LOCATION,
        app_name=cfg.app_name, tags=cfg.tags,
        repo_url=cfg.repo_url, dashboard_url=cfg.dashboard_url,
        witness_url=cfg.witness_url, methodology_url=cfg.methodology_url,
        custom_json_id=cfg.custom_json_id,
        cover_image_url=cover_url,
        chain_reference=None,  # dry-run: fall back to "broadcast log" wording
    )

    # Persist the rendered body to a .md file alongside the image so the
    # operator can review it in any editor that handles UTF-8 (every
    # modern one). Also keep a header dump for the metadata.
    md_path = cfg.image_dir / f"{day_str}.md"
    md_path.write_text(
        f"<!-- TITLE:    {post.title} -->\n"
        f"<!-- PERMLINK: {post.permlink} -->\n"
        f"<!-- TAGS:     {post.json_metadata['tags']} -->\n\n"
        + post.body,
        encoding="utf-8",
    )

    print(f"\n== cover image: {image_path} ({image_path.stat().st_size:,} bytes)")
    print(f"== rendered post: {md_path} ({md_path.stat().st_size:,} bytes)")
    print(f"== observations generated: {len(obs_list)}")
    for o in obs_list:
        # Substitute the Unicode arrows so a cp1252 terminal can still
        # print the summary line.
        marker = {"positive": "+", "negative": "-", "neutral": "."}.get(o.severity, "?")
        print(f"   {marker} [{o.severity:8s}] {o.category:22s} {o.headline}")

    print("\n" + "=" * 78)
    print(f"TITLE:    {post.title}")
    print(f"PERMLINK: {post.permlink}")
    print(f"TAGS:     {post.json_metadata['tags']}")
    print("=" * 78)
    print(f"\nFull body written to: {md_path}")
    print(f"Cover image at: {image_path}")
    print(f"(open in browser via: file:///{image_path.as_posix()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
