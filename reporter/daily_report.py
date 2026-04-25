"""Daily-report CLI entry.

Invoked by the systemd timer (`deploy/steemapps-reporter.timer`) once per
day at 02:30 UTC. Reports on the UTC day that ended two and a half hours
earlier, so by the time the report runs the window's last tick has long
since been written.

Usage:

    python -m reporter.daily_report                    # normal run
    python -m reporter.daily_report --dry-run          # force dev mode
    python -m reporter.daily_report --date 2026-04-23  # explicit window
    python -m reporter.daily_report --seed-synthetic   # seed the local DB
                                                       # with 24h of demo
                                                       # data (dev only)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import config as monitor_config
import database
import logger as logger_mod
import participants as participants_mod

from reporter import aggregation, broadcast, image_generator, observations, query, template
from reporter.config import MODE_DEV, MODE_PROD, ReporterConfig, load


log = logger_mod.get("reporter")


def _parse_day(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"invalid --date value {s!r}: {exc}")


def _force_dev(cfg: ReporterConfig) -> ReporterConfig:
    """Return a copy of cfg with mode forced to dev.

    Also redirects the image output to a tmp directory and clears the
    public URL — a dry-run must never embed a path the public cannot
    actually fetch."""
    from dataclasses import replace
    tmp = Path(tempfile.gettempdir()) / "steemapps-reports"
    return replace(cfg, mode=MODE_DEV, image_dir=tmp, image_url_base=None)


def _build_per_node(cfg: ReporterConfig, day: date, nodes_map: dict[str, Optional[str]]) -> dict[str, aggregation.NodeStats]:
    """Aggregate one UTC day. Returns {} when the window has no data."""
    s, e = query.utc_day_window(day)
    rows = query.fetch_measurements_in_window(cfg.db_path, s, e)
    if not rows:
        return {}
    grouped = query.group_by_node(rows)
    return {
        url: aggregation.aggregate_node(rs, url=url, region=nodes_map.get(url))
        for url, rs in grouped.items()
    }


def _build_week_history(
    cfg: ReporterConfig, day: date, nodes_map: dict[str, Optional[str]]
) -> list[dict[str, aggregation.NodeStats]]:
    """Per-day aggregates for the seven days before `day`, oldest first.

    Days that yielded zero rows are skipped — the observation engine
    treats anything shorter than WEEK_HISTORY_MIN_DAYS as "not enough
    history" and silently omits the week-anchored items."""
    out = []
    for offset in range(7, 0, -1):
        per_node = _build_per_node(cfg, day - timedelta(days=offset), nodes_map)
        if per_node:
            out.append(per_node)
    return out


def _load_nodes_map() -> dict[str, Optional[str]]:
    """Return `{url: region}` from nodes.json for the region column in the report."""
    return {n["url"]: n.get("region") for n in monitor_config.load_nodes()}


def _load_source_to_region(db_path: Path) -> dict[str, str]:
    """Build {source_location → region} for cross-region variance.

    The `source_location` column on each measurement row carries the
    primary monitor's `SOURCE_LOCATION` for self-poll rows and each
    participant's `display_label` for ingested rows. Mirroring that
    mapping back to the geographic region needs both the primary's
    config block and the participants table — rows whose source we
    can't map (legacy 'demo' rows from --seed-synthetic, deactivated
    participants) just don't appear in the cross-region cut.
    """
    mapping: dict[str, str] = {}
    primary = monitor_config.PRIMARY_SOURCE
    if primary.get("region"):
        # Both the production source label and the display label may
        # appear in the source_location column depending on how the
        # monitor was configured at write time. Keep both keys.
        mapping[primary["label"]] = primary["region"]
        if primary.get("display_label"):
            mapping[primary["display_label"]] = primary["region"]
    try:
        for p in participants_mod.list_participants(db_path=db_path):
            if p.region:
                mapping[p.display_label] = p.region
    except Exception:
        # Participants table missing on a fresh dev DB → just no
        # community sources to map. The rest of the report still works.
        log.exception("could not load participants for cross-region mapping")
    return mapping


def _build_daily_rows_history(
    cfg: ReporterConfig, day: date, days_back: int = 30
) -> list[dict[str, list[dict]]]:
    """Per-day {url: [rows]} dicts, oldest first, for the reliability
    ranking. Skips days that returned zero rows so the ranking covers
    the actual history span, not a padded window with empty days.
    """
    out: list[dict[str, list[dict]]] = []
    for offset in range(days_back, 0, -1):
        d = day - timedelta(days=offset - 1)         # include `day` itself
        s, e = query.utc_day_window(d)
        rows = query.fetch_measurements_in_window(cfg.db_path, s, e)
        if not rows:
            continue
        out.append(query.group_by_node(rows))
    return out


def run(day_arg: Optional[str], force_dry_run: bool, image_only: bool = False) -> int:
    """Main orchestration. Returns a shell exit code.

    `image_only` skips both broadcasts and the markdown render; it just
    generates the cover PNG and prints its path. Used by the local
    preview workflow."""
    cfg = load()
    if force_dry_run or image_only:
        cfg = _force_dev(cfg)
    logger_mod.setup()

    # Window — explicit --date wins; otherwise yesterday UTC.
    day = _parse_day(day_arg) if day_arg else query.previous_utc_day()
    start_iso, end_iso = query.utc_day_window(day)
    day_str = day.isoformat()

    log.info("mode=%s account=@%s day=%s window=[%s, %s)",
             cfg.mode, cfg.account, day_str, start_iso, end_iso)
    log.info("db_path=%s", cfg.db_path)

    rows = query.fetch_measurements_in_window(cfg.db_path, start_iso, end_iso)
    log.info("fetched %d measurement rows for the window", len(rows))
    if not rows:
        log.error("no data in window — refusing to post an empty report")
        return 2

    rows_by_node = query.group_by_node(rows)
    nodes_map = _load_nodes_map()

    per_node: dict[str, aggregation.NodeStats] = {}
    for url, node_rows in rows_by_node.items():
        per_node[url] = aggregation.aggregate_node(
            node_rows, url=url, region=nodes_map.get(url)
        )
    global_stats = aggregation.aggregate_global(per_node, rows_by_node)

    # Cover image — generate before anything that talks to the chain so a
    # broken Pillow path fails the run early, not after a custom_json hit.
    image_path = cfg.image_dir / f"{day_str}.png"
    image_generator.render_daily_image(day=day_str, per_node=per_node, output_path=image_path)
    log.info("cover image written: %s", image_path)
    cover_url = f"{cfg.image_url_base}/{day_str}.png" if cfg.image_url_base else None

    # Etappe-12a aggregations — pure functions over rows we already
    # have in memory. Cheap.
    latency_distribution = aggregation.compute_latency_distribution(rows)
    hour_pattern = aggregation.compute_hour_pattern(rows)
    error_breakdown = aggregation.compute_error_breakdown(per_node)
    source_to_region = _load_source_to_region(cfg.db_path)
    cross_region = aggregation.compute_cross_region_variance(rows_by_node, source_to_region)
    log.info(
        "etappe12a aggregates: dist=%d samples, hours=%d/24 populated, "
        "errors=%d total, cross_region=%d entries",
        latency_distribution.sample_size,
        sum(1 for b in hour_pattern.buckets if b.avg_latency_ms is not None),
        error_breakdown.total_errors,
        len(cross_region.entries),
    )

    # Detail image — second PNG with the three charts. Same fail-early
    # contract as the cover image (rendered before any broadcast).
    detail_image_path = cfg.image_dir / f"{day_str}-detail.png"
    image_generator.render_detail_image(
        day=day_str,
        per_node=per_node,
        hour_pattern=hour_pattern,
        cross_region=cross_region if cross_region.entries else None,
        output_path=detail_image_path,
    )
    log.info("detail image written: %s", detail_image_path)
    detail_url = f"{cfg.image_url_base}/{day_str}-detail.png" if cfg.image_url_base else None

    if image_only:
        # Print both paths (cover + detail) so the caller can `open` /
        # `xdg-open` either.
        print(str(image_path))
        print(str(detail_image_path))
        return 0

    # Week-over-week — pull the seven-day windows on each side.
    cur_start, _ = query.utc_day_window(day - timedelta(days=6))
    _, cur_end = query.utc_day_window(day)
    prev_start, _ = query.utc_day_window(day - timedelta(days=13))
    _, prev_end = query.utc_day_window(day - timedelta(days=7))
    cur_rows = query.fetch_measurements_in_window(cfg.db_path, cur_start, cur_end)
    prev_rows = query.fetch_measurements_in_window(cfg.db_path, prev_start, prev_end)
    week = aggregation.compare_weeks(
        query.group_by_node(cur_rows),
        query.group_by_node(prev_rows),
    )

    # Observations — yesterday + the seven prior days for trend analysis.
    yesterday_per_node = _build_per_node(cfg, day - timedelta(days=1), nodes_map) or None
    week_history = _build_week_history(cfg, day, nodes_map)
    obs_list = observations.gather_observations(
        per_node, global_stats,
        yesterday_per_node=yesterday_per_node,
        week_history=week_history,
    )
    log.info("observations: %d generated (categories: %s)",
             len(obs_list), ", ".join(o.category for o in obs_list))

    # Performance gap needs the previous-week-aligned reference window
    # (same 24 h slot, 7 days earlier). Re-using `_build_per_node` keeps
    # the lookback consistent with the existing week-over-week math.
    prev_per_node = _build_per_node(cfg, day - timedelta(days=7), nodes_map) or None
    performance_gap = aggregation.compute_performance_gap(per_node, prev_per_node)

    # Reliability ranking — dynamic-window. Walks back up to 30 days and
    # uses whatever history actually has data; the template skips the
    # section silently below 7 days (see _reliability_ranking_section).
    reliability_history = _build_daily_rows_history(cfg, day, days_back=30)
    reliability = aggregation.compute_reliability_ranking(reliability_history)
    log.info("reliability: %d days available, top=%d entries, longest_streak=%d",
             reliability.days_actual, len(reliability.top), reliability.longest_streak_days)

    # Build the `custom_json` payload up-front — it does not depend on any
    # chain reference, so it can go out first. Etappe-12a additions:
    # P50/P99 are inside `latency_ms` (already added by aggregation), and
    # the error_breakdown summary rides on `summary.error_breakdown`.
    payload = aggregation.to_custom_json_payload(
        day=day_str,
        window_start=start_iso,
        window_end=end_iso,
        source_location=monitor_config.SOURCE_LOCATION,
        methodology_version=monitor_config.METHODOLOGY_VERSION,
        per_node=per_node,
        global_stats=global_stats,
        error_breakdown=error_breakdown,
    )

    # Step 1 — custom_json. Pin raw data to chain before we reference it.
    try:
        custom_json_result = broadcast.broadcast_custom_json(cfg, payload)
        log.info("custom_json broadcast: tx=%s block=%d",
                 custom_json_result.tx_hash, custom_json_result.block_num)
    except broadcast.BroadcastError as exc:
        log.error("custom_json broadcast failed: %s", exc)
        return 3

    # Dev mode: the broadcast wrapper returns a placeholder ref; pass None
    # so the template falls back to "transaction in this report's broadcast
    # log" rather than embedding the dummy 'dry-run-custom-json' string.
    chain_ref = None if cfg.is_dev else broadcast.to_chain_reference(custom_json_result)

    # Step 2 — comment. Renders with the live tx hash so the post body
    # contains a precise pointer to the on-chain raw data.
    post = template.render(
        day=day_str,
        window_start=start_iso,
        window_end=end_iso,
        per_node=per_node,
        global_stats=global_stats,
        week=week,
        observations=obs_list,
        source_location=monitor_config.SOURCE_LOCATION,
        app_name=cfg.app_name,
        tags=cfg.tags,
        repo_url=cfg.repo_url,
        dashboard_url=cfg.dashboard_url,
        witness_url=cfg.witness_url,
        methodology_url=cfg.methodology_url,
        custom_json_id=cfg.custom_json_id,
        cover_image_url=cover_url,
        chain_reference=chain_ref,
        # Etappe-12a: extended sections + detail image. None-safe; the
        # template skips any section whose input is empty.
        latency_distribution=latency_distribution,
        hour_pattern=hour_pattern,
        error_breakdown=error_breakdown,
        performance_gap=performance_gap,
        cross_region=cross_region if cross_region.entries else None,
        reliability=reliability,
        detail_image_url=detail_url,
    )

    try:
        comment_result = broadcast.broadcast_comment(cfg, post)
        log.info("comment broadcast: tx=%s block=%d",
                 comment_result.tx_hash, comment_result.block_num)
    except broadcast.BroadcastError as exc:
        log.error("comment broadcast failed: %s", exc)
        return 4

    log.info("daily report complete for %s", day_str)
    return 0


def _seed_synthetic(db_path: Path) -> None:
    """Populate a local DB with 14 days of realistic-looking demo data.

    Used to produce a dry-run sample for the author when the real VM
    database is not reachable. Not wired into production in any way. Uses
    a single bulk `executemany` rather than row-at-a-time insert —
    14 days × 24 h × 60 min × 10 nodes ≈ 200 k rows, and the per-call
    connection overhead in `database.insert_measurement` would take
    minutes for that volume.
    """
    import random as _r
    import sqlite3

    database.initialise(db_path)
    nodes = monitor_config.load_nodes()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    profiles = {}
    for i, n in enumerate(nodes):
        _r.seed(1000 + i)
        profiles[n["url"]] = {
            "base_latency": _r.randint(120, 900),
            "jitter": _r.randint(30, 200),
            "fail_rate": _r.choice([0.001, 0.005, 0.01, 0.02, 0.05]),
        }
    _r.seed(42)
    base_block = 105_500_000
    minutes = 14 * 24 * 60

    rows: list[tuple] = []
    for m in range(minutes):
        ts = (now - timedelta(minutes=minutes - m)).isoformat().replace("+00:00", "Z")
        tick_block = base_block + m * 2
        for n in nodes:
            p = profiles[n["url"]]
            if _r.random() < p["fail_rate"]:
                rows.append((
                    ts, n["url"], 0, None, None,
                    _r.choice(["timeout", "HTTP 502", "connect_error: demo"]),
                    "demo",
                ))
            else:
                lat = max(40, int(_r.gauss(p["base_latency"], p["jitter"])))
                height = tick_block - _r.randint(0, 2)
                rows.append((
                    ts, n["url"], 1, lat, height, None, "demo",
                ))

    conn = sqlite3.connect(str(db_path), timeout=10.0, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("BEGIN")
        conn.executemany(
            "INSERT INTO measurements "
            "(timestamp, node_url, success, latency_ms, block_height, error_message, source_location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    log.info("seeded %d synthetic rows across %d nodes × %d minutes",
             len(rows), len(nodes), minutes)


def main(argv: list[str] | None = None) -> int:
    # The dev-mode output contains Unicode the post body uses (em-dashes,
    # the `Δ` glyph in the week-over-week section). On Linux stdout is
    # UTF-8 by default; Windows consoles often default to cp1252 and
    # would crash on `print(body)`. `reconfigure` is a no-op on a stream
    # that is already UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    ap = argparse.ArgumentParser(description="Steem API monitor daily report")
    ap.add_argument("--date", help="UTC date (YYYY-MM-DD), default: yesterday")
    ap.add_argument("--dry-run", action="store_true",
                    help="force dev mode (no chain transactions)")
    ap.add_argument("--seed-synthetic", action="store_true",
                    help="populate the local DB with 14 days of demo data")
    ap.add_argument("--image-only", action="store_true",
                    help="generate the cover PNG only and print its path; no broadcast")
    args = ap.parse_args(argv)

    if args.seed_synthetic:
        _seed_synthetic(monitor_config.DB_PATH)
        return 0
    return run(day_arg=args.date, force_dry_run=args.dry_run, image_only=args.image_only)


if __name__ == "__main__":
    sys.exit(main())
