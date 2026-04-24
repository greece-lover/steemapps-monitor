"""FastAPI surface.

Phase 3 kept this minimal; Phase 4 adds the fields the dashboard needs
while the API stays loopback-only (binding handled in monitor.py):

- `GET /api/v1/health`                           — is the monitor alive?
- `GET /api/v1/status`                           — current score + last-tick data per node
- `GET /api/v1/nodes/{url}/history?hours=1`      — lean time-ordered points for sparkline charts
- `GET /api/v1/nodes/{url}/uptime?days=7`        — success-rate over a day window

CORS is enabled so the dashboard served from a different origin (e.g.
file://, a local dev server, or later the production server) can call the API
through an SSH tunnel without proxy games.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import config
import database
import scoring
from cache import ttl_cache


# Tracked so /health can report how long the process has been up.
_BOOT_TS = time.time()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _reference_block(latest_by_node: dict[str, dict]) -> Optional[int]:
    """Pick the chain-height reference — max head block across successful ticks."""
    heights = [
        row["block_height"]
        for row in latest_by_node.values()
        if row.get("success") and row.get("block_height") is not None
    ]
    return max(heights) if heights else None


# --- Phase 6 helpers --------------------------------------------------------

_RANGE_TO_MINUTES = {"24h": 24 * 60, "7d": 7 * 24 * 60, "30d": 30 * 24 * 60}


def _range_minutes(range_str: str) -> int:
    if range_str not in _RANGE_TO_MINUTES:
        raise HTTPException(status_code=400, detail=f"range must be one of {list(_RANGE_TO_MINUTES)}")
    return _RANGE_TO_MINUTES[range_str]


def _percentile(values: list[int], p: float) -> Optional[float]:
    """Linear-interpolation percentile; returns None for empty input."""
    if not values:
        return None
    sd = sorted(values)
    if len(sd) == 1:
        return float(sd[0])
    k = (len(sd) - 1) * p / 100.0
    floor = int(k)
    ceil = min(floor + 1, len(sd) - 1)
    return round(sd[floor] + (k - floor) * (sd[ceil] - sd[floor]), 1)


def _downsample(points: list[dict], max_points: int = 1500) -> list[dict]:
    """Bucket-average a chronological point series down to at most `max_points`.

    Within each bucket we keep the middle row's timestamp, the average of the
    non-null latencies, and `success=False` if any sample in the bucket failed
    (so outage markers aren't smoothed away into a misleading dip)."""
    n = len(points)
    if n <= max_points:
        return points
    bucket_size = n / max_points
    out: list[dict] = []
    for i in range(max_points):
        lo = int(i * bucket_size)
        hi = int((i + 1) * bucket_size)
        bucket = points[lo:hi]
        if not bucket:
            continue
        mid = bucket[len(bucket) // 2]
        lats = [p["latency_ms"] for p in bucket if p.get("latency_ms") is not None]
        all_ok = all(p.get("success") for p in bucket)
        out.append({
            "ts": mid["ts"],
            "latency_ms": round(sum(lats) / len(lats)) if lats else None,
            "success": all_ok,
        })
    return out


def build_app() -> FastAPI:
    app = FastAPI(
        title="steemapps-monitor",
        version="0.1.0",
        docs_url="/api/v1/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )

    # The dashboard will be served from a separate origin during Phase 4
    # (file://, a production-hosted static site later on). Since the API is
    # read-only and has no authentication, wildcard CORS is safe.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health() -> dict:
        # Resolve DB_PATH at call time so tests can redirect both the
        # default and this attribute to a temp file via monkeypatch.
        latest = database.get_latest_per_node(database.DB_PATH)
        last_tick_ts = None
        if latest:
            last_tick_ts = max(row["timestamp"] for row in latest.values())
        return {
            "service": "steemapps-monitor",
            "status": "ok",
            "uptime_s": int(time.time() - _BOOT_TS),
            "last_tick_ts": last_tick_ts,
            "methodology_version": config.METHODOLOGY_VERSION,
            "now": _utcnow_iso(),
        }

    @app.get("/api/v1/status")
    def status() -> dict:
        nodes = config.load_nodes()
        latest = database.get_latest_per_node(database.DB_PATH)
        ref_block = _reference_block(latest)
        result_nodes = []
        for n in nodes:
            url = n["url"]
            last = latest.get(url)
            if last is None:
                result_nodes.append({
                    "url": url,
                    "region": n.get("region"),
                    "status": "unknown",
                    "score": None,
                    "last_tick_ts": None,
                    "latency_ms": None,
                    "block_height": None,
                    "block_lag": None,
                    "error_message": None,
                    "reasons": [],
                })
                continue
            # Score uses the last 20 ticks for the error-rate rule; this is
            # the same lookback the methodology doc uses for `mv1`.
            recent = database.get_recent_measurements(url, limit=20, db_path=database.DB_PATH)
            breakdown = scoring.calculate_score(
                recent,
                reference_block=ref_block,
                current_ok=bool(last["success"]),
                current_latency_ms=last.get("latency_ms"),
                current_block_height=last.get("block_height"),
            )
            block_lag = None
            if ref_block is not None and last.get("block_height") is not None:
                block_lag = ref_block - int(last["block_height"])
            result_nodes.append({
                "url": url,
                "region": n.get("region"),
                "status": scoring.status_label(breakdown.score, bool(last["success"])),
                "score": breakdown.score,
                "last_tick_ts": last["timestamp"],
                "latency_ms": last.get("latency_ms"),
                "block_height": last.get("block_height"),
                "block_lag": block_lag,
                "error_message": last.get("error_message"),
                "reasons": breakdown.reasons,
            })
        return {
            "generated_at": _utcnow_iso(),
            "methodology_version": config.METHODOLOGY_VERSION,
            "reference_block": ref_block,
            "nodes": result_nodes,
        }

    @app.get("/api/v1/nodes/{node_url:path}/history")
    def node_history(node_url: str, hours: int = Query(1, ge=1, le=168)) -> dict:
        """Sparkline-friendly time series.

        Returns points in chronological order (oldest first) with a minimal
        shape — just what a line chart needs — so a one-hour window is a
        ~60-row payload instead of a ~60-row-of-full-rows payload.
        """
        # URL in path is percent-encoded by the client (dashboard, curl),
        # so decode before matching against the DB.
        url = unquote(node_url)
        nodes = {n["url"] for n in config.load_nodes()}
        if url not in nodes:
            raise HTTPException(status_code=404, detail=f"unknown node: {url}")
        # 1 tick per minute, so cap = hours * 60.
        raw = database.get_recent_measurements(url, limit=hours * 60, db_path=database.DB_PATH)
        # Reverse to chronological order.
        raw.reverse()
        points = [
            {
                "ts": r["timestamp"],
                "latency_ms": r["latency_ms"],
                "success": bool(r["success"]),
            }
            for r in raw
        ]
        return {
            "node_url": url,
            "hours": hours,
            "methodology_version": config.METHODOLOGY_VERSION,
            "points": points,
        }

    @app.get("/api/v1/nodes/{node_url:path}/uptime")
    def node_uptime(node_url: str, days: int = Query(1, ge=1, le=30)) -> dict:
        """Success-rate over a day window.

        Computed from the same raw rows as `/status` — one call gives the
        dashboard both the "24 h" and "7 d" cards without any client-side
        aggregation.
        """
        url = unquote(node_url)
        nodes = {n["url"] for n in config.load_nodes()}
        if url not in nodes:
            raise HTTPException(status_code=404, detail=f"unknown node: {url}")
        stats = database.get_uptime_stats(url, lookback_minutes=days * 24 * 60, db_path=database.DB_PATH)
        return {
            "node_url": url,
            "days": days,
            "total": stats["total"],
            "ok": stats["ok"],
            "uptime_pct": stats["uptime_pct"],
        }

    # ------------------------------------------------------------------ #
    #  Phase 6 endpoints.                                                #
    # ------------------------------------------------------------------ #
    # Helpers are defined inside build_app() so each built app owns its
    # own cache — test fixtures that build a fresh app in setUp therefore
    # start with an empty cache automatically.

    @ttl_cache(30)
    def _detail_data(node_url: str, lookback_minutes: int, db_path_key: str) -> dict:
        rows = database.get_measurements_range(node_url, lookback_minutes, db_path=db_path_key)
        points_full = [
            {"ts": r["timestamp"], "latency_ms": r["latency_ms"], "success": bool(r["success"])}
            for r in rows
        ]
        lag_points_full = []
        if rows:
            # block_lag is not stored; derive against the max head block seen
            # inside the window so a long window stays internally consistent.
            heights = [r["block_height"] for r in rows if r.get("block_height") is not None]
            ref_block = max(heights) if heights else None
            for r in rows:
                if not r.get("success") or r.get("block_height") is None or ref_block is None:
                    continue
                lag_points_full.append({
                    "ts": r["timestamp"],
                    "block_lag": max(0, ref_block - int(r["block_height"])),
                })
        ok_rows = [r for r in rows if r["success"]]
        latencies = [int(r["latency_ms"]) for r in ok_rows if r.get("latency_ms") is not None]
        total = len(rows)
        ok = sum(1 for r in rows if r["success"])
        outages = database.compute_outages(rows)
        return {
            "points": _downsample(points_full),
            "block_lag_points": _downsample(lag_points_full),
            "uptime": {
                "total": total,
                "ok": ok,
                "uptime_pct": round(100.0 * ok / total, 2) if total else 0.0,
            },
            "latency_stats": {
                "min": min(latencies) if latencies else None,
                "max": max(latencies) if latencies else None,
                "avg": round(sum(latencies) / len(latencies), 1) if latencies else None,
                "p50": _percentile(latencies, 50),
                "p95": _percentile(latencies, 95),
                "p99": _percentile(latencies, 99),
                "sample_size": len(latencies),
            },
            "outages_summary": {
                "total": len(outages),
                "real": sum(1 for o in outages if o["severity"] == "real"),
                "short": sum(1 for o in outages if o["severity"] == "short"),
            },
        }

    @ttl_cache(60)
    def _node_outages(node_url: str, lookback_minutes: int, db_path_key: str) -> list[dict]:
        rows = database.get_measurements_range(node_url, lookback_minutes, db_path=db_path_key)
        return database.compute_outages(rows)

    @ttl_cache(60)
    def _global_outages(lookback_minutes: int, db_path_key: str) -> list[dict]:
        """Compute outages for every node in one scan of the window.

        `get_all_measurements_range` orders rows by node_url then timestamp;
        we bucket by node_url and run `compute_outages` per bucket."""
        rows = database.get_all_measurements_range(lookback_minutes, db_path=db_path_key)
        out: list[dict] = []
        current_node: Optional[str] = None
        bucket: list[dict] = []
        now_iso = _utcnow_iso()
        for r in rows:
            if r["node_url"] != current_node:
                if bucket:
                    for o in database.compute_outages(bucket, now_iso=now_iso):
                        o["node_url"] = current_node
                        out.append(o)
                current_node = r["node_url"]
                bucket = []
            bucket.append(r)
        if bucket and current_node is not None:
            for o in database.compute_outages(bucket, now_iso=now_iso):
                o["node_url"] = current_node
                out.append(o)
        out.sort(key=lambda o: o["start"], reverse=True)
        return out

    @ttl_cache(60)
    def _rankings(metric: str, lookback_minutes: int, db_path_key: str) -> list[dict]:
        aggs = database.get_per_node_aggregates(lookback_minutes, db_path=db_path_key)
        regions = {n["url"]: n.get("region") for n in config.load_nodes()}
        enriched = [{**a, "region": regions.get(a["node_url"])} for a in aggs]
        if metric == "latency":
            enriched = [e for e in enriched if e["avg_latency_ms"] is not None]
            enriched.sort(key=lambda e: e["avg_latency_ms"])
        elif metric == "uptime":
            enriched.sort(key=lambda e: e["uptime_pct"], reverse=True)
        elif metric == "errors":
            enriched.sort(key=lambda e: e["errors"], reverse=True)
        else:
            raise HTTPException(status_code=400, detail="metric must be latency|uptime|errors")
        return enriched

    def _validate_node(url: str) -> None:
        known = {n["url"] for n in config.load_nodes()}
        if url not in known:
            raise HTTPException(status_code=404, detail=f"unknown node: {url}")

    @app.get("/api/v1/nodes/{node_url:path}/detail")
    def node_detail(node_url: str, range: str = Query("24h", pattern="^(24h|7d|30d)$")) -> dict:
        """Per-node detail view — points, block-lag, uptime, percentiles, outage summary."""
        url = unquote(node_url)
        _validate_node(url)
        minutes = _range_minutes(range)
        data = _detail_data(url, minutes, str(database.DB_PATH))
        return {
            "node_url": url,
            "range": range,
            "generated_at": _utcnow_iso(),
            "methodology_version": config.METHODOLOGY_VERSION,
            **data,
        }

    @app.get("/api/v1/nodes/{node_url:path}/outages")
    def node_outages(
        node_url: str,
        range: str = Query("7d", pattern="^(24h|7d|30d)$"),
        limit: int = Query(100, ge=1, le=500),
        severity: Optional[str] = Query(None, pattern="^(short|real)$"),
    ) -> dict:
        """Outage list for a single node in the requested window."""
        url = unquote(node_url)
        _validate_node(url)
        minutes = _range_minutes(range)
        outages = _node_outages(url, minutes, str(database.DB_PATH))
        if severity:
            outages = [o for o in outages if o["severity"] == severity]
        # Newest first, capped.
        outages = sorted(outages, key=lambda o: o["start"], reverse=True)[:limit]
        return {
            "node_url": url,
            "range": range,
            "severity_filter": severity,
            "severity_threshold_s": database.OUTAGE_SEVERITY_THRESHOLD_S,
            "generated_at": _utcnow_iso(),
            "outages": outages,
        }

    @app.get("/api/v1/outages")
    def outages_global(
        range: str = Query("7d", pattern="^(24h|7d|30d)$"),
        node: Optional[str] = None,
        severity: Optional[str] = Query(None, pattern="^(short|real)$"),
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict:
        """Outages across every node. Filter by node, severity, window."""
        minutes = _range_minutes(range)
        outages = _global_outages(minutes, str(database.DB_PATH))
        if node:
            _validate_node(node)
            outages = [o for o in outages if o["node_url"] == node]
        if severity:
            outages = [o for o in outages if o["severity"] == severity]
        return {
            "range": range,
            "node_filter": node,
            "severity_filter": severity,
            "severity_threshold_s": database.OUTAGE_SEVERITY_THRESHOLD_S,
            "generated_at": _utcnow_iso(),
            "outages": outages[:limit],
        }

    @app.get("/api/v1/stats/top")
    def stats_top(
        metric: str = Query("latency", pattern="^(latency|uptime|errors)$"),
        limit: int = Query(10, ge=1, le=50),
        range: str = Query("24h", pattern="^(24h|7d|30d)$"),
    ) -> dict:
        """Top-N ranking by latency (asc), uptime (desc) or errors (desc)."""
        minutes = _range_minutes(range)
        ranked = _rankings(metric, minutes, str(database.DB_PATH))
        return {
            "metric": metric,
            "range": range,
            "limit": limit,
            "generated_at": _utcnow_iso(),
            "ranked": ranked[:limit],
        }

    return app


# Let uvicorn import `api:app` without needing to call build_app() ourselves.
app = build_app()
