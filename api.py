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

import secrets
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

import config
import database
import ingest as ingest_mod
import join as join_mod
import participants as participants_mod
import scoring
from cache import ttl_cache


# Tracked so /health can report how long the process has been up.
_BOOT_TS = time.time()


# -----------------------------------------------------------------
# Pydantic models for request bodies. Defined at module scope so
# FastAPI's OpenAPI introspection picks them up correctly — when
# the same class is declared inside build_app() the parameter
# resolution falls back to "single string query param" and rejects
# every POST with a 422 missing-field error.
# -----------------------------------------------------------------


class IngestMeasurement(BaseModel):
    timestamp: str
    node_url: str
    success: bool
    latency_ms: Optional[int] = None
    block_height: Optional[int] = None
    error_category: Optional[str] = None


class IngestRequest(BaseModel):
    measurements: list[IngestMeasurement] = Field(min_length=1, max_length=ingest_mod.MAX_BATCH_SIZE)


class ParticipantCreate(BaseModel):
    steem_account: str = Field(min_length=2, max_length=32)
    display_label: str = Field(min_length=1, max_length=64)
    region: Optional[str] = Field(default=None, max_length=32)
    note: Optional[str] = Field(default=None, max_length=200)


class ParticipantPatch(BaseModel):
    active: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=200)


class JoinRegisterRequest(BaseModel):
    steem_account: str = Field(min_length=3, max_length=16)
    display_label: str = Field(min_length=1, max_length=64)
    region: str = Field(min_length=1, max_length=32)


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

_RANGE_TO_MINUTES = {
    "24h": 24 * 60,
    "7d":  7 * 24 * 60,
    "30d": 30 * 24 * 60,
    "90d": 90 * 24 * 60,
}


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
                    "category": n.get("category", "live"),
                    "description": n.get("description"),
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
                "category": n.get("category", "live"),
                "description": n.get("description"),
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
        elif metric == "latency_worst":
            enriched = [e for e in enriched if e["avg_latency_ms"] is not None]
            enriched.sort(key=lambda e: e["avg_latency_ms"], reverse=True)
        elif metric == "uptime":
            enriched.sort(key=lambda e: e["uptime_pct"], reverse=True)
        elif metric == "uptime_worst":
            enriched.sort(key=lambda e: e["uptime_pct"])
        elif metric == "errors":
            enriched.sort(key=lambda e: e["errors"], reverse=True)
        else:
            raise HTTPException(status_code=400, detail="metric must be latency|latency_worst|uptime|uptime_worst|errors")
        return enriched

    @ttl_cache(60)
    def _chain_availability(lookback_minutes: int, bucket_seconds: int, db_path_key: str) -> list[dict]:
        return database.get_chain_availability(lookback_minutes, bucket_seconds, db_path=db_path_key)

    @ttl_cache(60)
    def _daily_comparison(db_path_key: str) -> dict:
        """Compare three past windows, each 24 h wide.

        - today     : last 24 h                                       (offset   0 ..  24 h)
        - yesterday : 24 h–48 h ago                                   (offset  24 h ..  48 h)
        - lastweek  : the same 24 h slice exactly one week earlier    (offset 168 h .. 192 h)
        """
        regions = {n["url"]: n.get("region") for n in config.load_nodes()}
        today = database.get_per_node_aggregates(24 * 60, db_path=db_path_key)
        yday = database.get_per_node_aggregates_between(48 * 60, 24 * 60, db_path=db_path_key)
        lastweek = database.get_per_node_aggregates_between(192 * 60, 168 * 60, db_path=db_path_key)

        def index(xs):
            return {x["node_url"]: x for x in xs}

        it = index(today)
        iy = index(yday)
        il = index(lastweek)
        out = []
        for url, region in regions.items():
            t = it.get(url, {})
            y = iy.get(url, {})
            l = il.get(url, {})
            out.append({
                "node_url": url,
                "region": region,
                "today": {
                    "avg_latency_ms": t.get("avg_latency_ms"),
                    "uptime_pct": t.get("uptime_pct", 0.0),
                    "total": t.get("total", 0),
                },
                "yesterday": {
                    "avg_latency_ms": y.get("avg_latency_ms"),
                    "uptime_pct": y.get("uptime_pct", 0.0),
                    "total": y.get("total", 0),
                },
                "lastweek": {
                    "avg_latency_ms": l.get("avg_latency_ms"),
                    "uptime_pct": l.get("uptime_pct", 0.0),
                    "total": l.get("total", 0),
                },
            })
        return {"nodes": out}

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
        range: str = Query("7d", pattern="^(24h|7d|30d|90d)$"),
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

    def _filtered_global_outages(
        range_str: str,
        node: Optional[str],
        severity: Optional[str],
        min_duration_s: int,
    ) -> list[dict]:
        """Shared filter pipeline for /outages and the export endpoints.
        Exposed as a helper so CSV/JSON exports reuse the exact same
        result set the UI sees."""
        minutes = _range_minutes(range_str)
        outages = _global_outages(minutes, str(database.DB_PATH))
        if node:
            _validate_node(node)
            outages = [o for o in outages if o["node_url"] == node]
        if severity:
            outages = [o for o in outages if o["severity"] == severity]
        if min_duration_s > 0:
            outages = [o for o in outages if o["duration_s"] >= min_duration_s]
        return outages

    @app.get("/api/v1/outages")
    def outages_global(
        range: str = Query("7d", pattern="^(24h|7d|30d|90d)$"),
        node: Optional[str] = None,
        severity: Optional[str] = Query(None, pattern="^(short|real)$"),
        min_duration_s: int = Query(0, ge=0, le=86400),
        limit: int = Query(100, ge=1, le=5000),
    ) -> dict:
        """Outages across every node. Filter by node, severity, window, duration."""
        outages = _filtered_global_outages(range, node, severity, min_duration_s)
        return {
            "range": range,
            "node_filter": node,
            "severity_filter": severity,
            "min_duration_s": min_duration_s,
            "severity_threshold_s": database.OUTAGE_SEVERITY_THRESHOLD_S,
            "generated_at": _utcnow_iso(),
            "total": len(outages),
            "outages": outages[:limit],
        }

    @ttl_cache(300)
    def _uptime_daily(node_url: str, days: int, db_path_key: str) -> list[dict]:
        sparse = database.get_uptime_daily(node_url, days, db_path=db_path_key)
        # Fill in missing days so the calendar is contiguous from
        # (today - days + 1) through today.
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        today = _dt.now(_tz.utc).date()
        by_day = {r["date"]: r for r in sparse}
        out = []
        for i in range(days):
            d = (today - _td(days=days - 1 - i)).isoformat()
            if d in by_day:
                out.append(by_day[d])
            else:
                out.append({"date": d, "total": 0, "ok": 0, "uptime_pct": None})
        return out

    @app.get("/api/v1/nodes/{node_url:path}/uptime-daily")
    def node_uptime_daily(node_url: str, days: int = Query(30, ge=1, le=90)) -> dict:
        """Per-day uptime for the calendar view on the node detail page."""
        url = unquote(node_url)
        _validate_node(url)
        data = _uptime_daily(url, days, str(database.DB_PATH))
        return {
            "node_url": url,
            "days": days,
            "generated_at": _utcnow_iso(),
            "uptime": data,
        }

    # ------------------------------------------------------------------ #
    #  CSV / JSON export of the outage log.                              #
    # ------------------------------------------------------------------ #

    def _outages_csv(outages: list[dict]) -> str:
        """Render the outage list as a minimal RFC 4180 CSV.

        Rolling our own writer keeps us dependency-free; the field set
        is small enough that we don't need the escaping logic of the
        stdlib csv module for anything beyond a double-quote rewrite.
        """
        def esc(v):
            if v is None:
                return ""
            s = str(v)
            if '"' in s or ',' in s or '\n' in s:
                return '"' + s.replace('"', '""') + '"'
            return s
        header = "node_url,start,end,duration_s,severity,error_sample,ongoing\n"
        rows = []
        for o in outages:
            rows.append(",".join([
                esc(o.get("node_url", "")),
                esc(o["start"]),
                esc(o["end"]),
                esc(o["duration_s"]),
                esc(o["severity"]),
                esc(o.get("error_sample")),
                esc("true" if o.get("ongoing") else "false"),
            ]))
        return header + "\n".join(rows) + ("\n" if rows else "")

    @app.get("/api/v1/export/outages.csv")
    def export_outages_csv(
        range: str = Query("30d", pattern="^(24h|7d|30d|90d)$"),
        node: Optional[str] = None,
        severity: Optional[str] = Query(None, pattern="^(short|real)$"),
        min_duration_s: int = Query(0, ge=0, le=86400),
        source: Optional[str] = None,
    ) -> Response:
        """CSV download of the filtered outage log. Reuses the exact
        filter pipeline of /api/v1/outages so what you download is what
        you see on the page. The `source` filter narrows to outages
        observed by one specific measurement source — the underlying
        outage detector still runs across the full fleet view first,
        and the source filter is applied to the resulting rows."""
        outages = _filtered_global_outages(range, node, severity, min_duration_s)
        if source:
            outages = [o for o in outages if o.get("source_location") == source]
        body = _outages_csv(outages)
        filename = f"outages-{range}"
        if node: filename += f"-{node.replace('https://','').replace('/','_')}"
        if severity: filename += f"-{severity}"
        if source: filename += f"-src-{source.replace(' ', '_')}"
        filename += ".csv"
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/v1/export/outages.json")
    def export_outages_json(
        range: str = Query("30d", pattern="^(24h|7d|30d|90d)$"),
        node: Optional[str] = None,
        severity: Optional[str] = Query(None, pattern="^(short|real)$"),
        min_duration_s: int = Query(0, ge=0, le=86400),
        source: Optional[str] = None,
    ) -> Response:
        """JSON download of the filtered outage log. Same filter
        pipeline as the CSV export; only the Content-Disposition and
        envelope differ."""
        import json as _json
        outages = _filtered_global_outages(range, node, severity, min_duration_s)
        if source:
            outages = [o for o in outages if o.get("source_location") == source]
        payload = {
            "range": range,
            "node_filter": node,
            "severity_filter": severity,
            "min_duration_s": min_duration_s,
            "source_filter": source,
            "severity_threshold_s": database.OUTAGE_SEVERITY_THRESHOLD_S,
            "generated_at": _utcnow_iso(),
            "total": len(outages),
            "outages": outages,
        }
        filename = f"outages-{range}"
        if node: filename += f"-{node.replace('https://','').replace('/','_')}"
        if severity: filename += f"-{severity}"
        if source: filename += f"-src-{source.replace(' ', '_')}"
        filename += ".json"
        return Response(
            content=_json.dumps(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ------------------------------------------------------------------ #
    #  Phase 6 Etappe 12b — bulk export endpoints                          #
    # ------------------------------------------------------------------ #
    # measurements: raw rows (csv/json/jsonl). aggregates: per-bucket
    # (csv/json/jsonl, hourly or daily). Both stream over a server-side
    # cursor so the API process holds at most one chunk in memory even
    # at the 90-day window cap.

    _EXPORT_RANGE_TO_MINUTES = {
        "24h": 24 * 60,
        "7d":  7 * 24 * 60,
        "30d": 30 * 24 * 60,
        "90d": 90 * 24 * 60,
    }

    def _export_window(range_str: str) -> tuple[str, str]:
        """Return (start_iso, end_iso) for the requested range. The
        upper bound is now-rounded-to-the-second so two consecutive
        downloads in the same minute share a stable boundary."""
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        now = _dt.now(_tz.utc).replace(microsecond=0)
        end = now + _td(seconds=1)                  # exclusive — include current second
        minutes = _EXPORT_RANGE_TO_MINUTES[range_str]
        start = now - _td(minutes=minutes)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        return start.strftime(fmt), end.strftime(fmt)

    def _csv_field(v) -> str:
        """Minimal RFC-4180 quoting — same convention as _outages_csv."""
        if v is None:
            return ""
        s = str(v)
        if '"' in s or ',' in s or '\n' in s:
            return '"' + s.replace('"', '""') + '"'
        return s

    @app.get("/api/v1/export/measurements")
    def export_measurements(
        range: str = Query("24h", pattern="^(24h|7d|30d|90d)$"),
        node: Optional[str] = None,
        source: Optional[str] = None,
        format: str = Query("csv", pattern="^(csv|json|jsonl)$"),
    ) -> StreamingResponse:
        """Streaming export of raw measurement rows.

        - `csv`   header row + one CSV line per measurement
        - `json`  pretty-printed JSON object with metadata + array
        - `jsonl` one JSON object per line (newline-delimited JSON)

        Filters: optional `node` (exact URL match) and `source`
        (exact source_location match). Use `/api/v1/export/sources`
        to enumerate available source labels.
        """
        if node:
            _validate_node(node)
        start_iso, end_iso = _export_window(range)

        if format == "csv":
            def _gen_csv():
                yield "timestamp,node_url,success,latency_ms,block_height,error_message,source_location\n"
                for r in database.stream_measurements(
                    start_iso=start_iso, end_iso=end_iso,
                    node_url=node, source_location=source,
                    db_path=database.DB_PATH,
                ):
                    yield ",".join([
                        _csv_field(r["timestamp"]),
                        _csv_field(r["node_url"]),
                        "1" if r["success"] else "0",
                        _csv_field(r["latency_ms"]),
                        _csv_field(r["block_height"]),
                        _csv_field(r["error_message"]),
                        _csv_field(r["source_location"]),
                    ]) + "\n"
            media_type = "text/csv; charset=utf-8"
            ext = "csv"
            body = _gen_csv()
        elif format == "jsonl":
            import json as _json
            def _gen_jsonl():
                for r in database.stream_measurements(
                    start_iso=start_iso, end_iso=end_iso,
                    node_url=node, source_location=source,
                    db_path=database.DB_PATH,
                ):
                    r["success"] = bool(r["success"])
                    yield _json.dumps(r) + "\n"
            media_type = "application/x-ndjson"
            ext = "jsonl"
            body = _gen_jsonl()
        else:                                      # format == "json"
            import json as _json
            envelope = {
                "range": range, "node_filter": node,
                "source_filter": source, "window": {"start": start_iso, "end": end_iso},
                "generated_at": _utcnow_iso(),
            }
            envelope_open = _json.dumps(envelope)[:-1]   # drop the closing brace
            def _gen_json():
                yield envelope_open + ", \"measurements\": ["
                first = True
                for r in database.stream_measurements(
                    start_iso=start_iso, end_iso=end_iso,
                    node_url=node, source_location=source,
                    db_path=database.DB_PATH,
                ):
                    r["success"] = bool(r["success"])
                    yield ("" if first else ",") + _json.dumps(r)
                    first = False
                yield "]}"
            media_type = "application/json"
            ext = "json"
            body = _gen_json()

        filename = f"measurements-{range}"
        if node: filename += f"-{node.replace('https://','').replace('/','_')}"
        if source: filename += f"-src-{source.replace(' ', '_')}"
        filename += f".{ext}"
        return StreamingResponse(
            body,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/v1/export/aggregates")
    def export_aggregates(
        range: str = Query("24h", pattern="^(24h|7d|30d|90d)$"),
        granularity: str = Query("hourly", pattern="^(hourly|daily)$"),
        node: Optional[str] = None,
        source: Optional[str] = None,
        format: str = Query("csv", pattern="^(csv|json|jsonl)$"),
    ) -> StreamingResponse:
        """Streaming export of pre-bucketed aggregates.

        Bucket key shape: `YYYY-MM-DDTHH:00:00Z` for hourly,
        `YYYY-MM-DD` for daily. One row per (bucket, node), with
        total / ok / errors / uptime_pct / avg/min/max latency.
        """
        if node:
            _validate_node(node)
        start_iso, end_iso = _export_window(range)

        if format == "csv":
            def _gen_csv():
                yield "bucket,node_url,total,ok,errors,uptime_pct,avg_latency_ms,min_latency_ms,max_latency_ms\n"
                for r in database.stream_aggregates(
                    start_iso=start_iso, end_iso=end_iso,
                    granularity=granularity,
                    node_url=node, source_location=source,
                    db_path=database.DB_PATH,
                ):
                    yield ",".join([
                        _csv_field(r["bucket"]),
                        _csv_field(r["node_url"]),
                        _csv_field(r["total"]),
                        _csv_field(r["ok"]),
                        _csv_field(r["errors"]),
                        _csv_field(r["uptime_pct"]),
                        _csv_field(r["avg_latency_ms"]),
                        _csv_field(r["min_latency_ms"]),
                        _csv_field(r["max_latency_ms"]),
                    ]) + "\n"
            media_type = "text/csv; charset=utf-8"
            ext = "csv"
            body = _gen_csv()
        elif format == "jsonl":
            import json as _json
            def _gen_jsonl():
                for r in database.stream_aggregates(
                    start_iso=start_iso, end_iso=end_iso,
                    granularity=granularity,
                    node_url=node, source_location=source,
                    db_path=database.DB_PATH,
                ):
                    yield _json.dumps(r) + "\n"
            media_type = "application/x-ndjson"
            ext = "jsonl"
            body = _gen_jsonl()
        else:                                      # format == "json"
            import json as _json
            envelope = {
                "range": range, "granularity": granularity,
                "node_filter": node, "source_filter": source,
                "window": {"start": start_iso, "end": end_iso},
                "generated_at": _utcnow_iso(),
            }
            envelope_open = _json.dumps(envelope)[:-1]
            def _gen_json():
                yield envelope_open + ", \"aggregates\": ["
                first = True
                for r in database.stream_aggregates(
                    start_iso=start_iso, end_iso=end_iso,
                    granularity=granularity,
                    node_url=node, source_location=source,
                    db_path=database.DB_PATH,
                ):
                    yield ("" if first else ",") + _json.dumps(r)
                    first = False
                yield "]}"
            media_type = "application/json"
            ext = "json"
            body = _gen_json()

        filename = f"aggregates-{granularity}-{range}"
        if node: filename += f"-{node.replace('https://','').replace('/','_')}"
        if source: filename += f"-src-{source.replace(' ', '_')}"
        filename += f".{ext}"
        return StreamingResponse(
            body,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/v1/export/sources")
    def export_sources_list() -> dict:
        """List the source_location values that have ever produced data.
        Powers the source-filter dropdown on data.html."""
        return {
            "generated_at": _utcnow_iso(),
            "sources": database.list_distinct_source_locations(database.DB_PATH),
        }

    @app.get("/api/v1/stats/top")
    def stats_top(
        metric: str = Query("latency", pattern="^(latency|latency_worst|uptime|uptime_worst|errors)$"),
        limit: int = Query(10, ge=1, le=50),
        range: str = Query("24h", pattern="^(24h|7d|30d|90d)$"),
    ) -> dict:
        """Top-N ranking by latency, uptime, errors. `latency_worst` / `uptime_worst` reverse the sort."""
        minutes = _range_minutes(range)
        ranked = _rankings(metric, minutes, str(database.DB_PATH))
        return {
            "metric": metric,
            "range": range,
            "limit": limit,
            "generated_at": _utcnow_iso(),
            "ranked": ranked[:limit],
        }

    @ttl_cache(60)
    def _regions_aggregate(db_path_key: str) -> dict:
        """Aggregate the fleet by region for the /regions endpoint.

        Uses current status (last tick per node) for the pill colour and
        the 24-hour aggregate for latency + uptime averages. Regions with
        no geographic anchor (global / unknown) still appear in the table
        but carry `lat`/`lng`=None, so map code must skip them."""
        nodes = config.load_nodes()
        latest = database.get_latest_per_node(db_path=db_path_key)
        aggs_24h = {a["node_url"]: a for a in database.get_per_node_aggregates(24 * 60, db_path=db_path_key)}
        aggs_7d = {a["node_url"]: a for a in database.get_per_node_aggregates(7 * 24 * 60, db_path=db_path_key)}
        ref = _reference_block(latest)

        # Group nodes by region, compute per-region aggregates.
        by_region: dict[str, list] = {}
        for n in nodes:
            by_region.setdefault(n.get("region") or "unknown", []).append(n)

        out = []
        for region, region_nodes in by_region.items():
            geo = config.REGION_COORDINATES.get(region, {"lat": None, "lng": None, "label": region})
            node_rows = []
            avg_latency_samples: list[int] = []
            uptime_pcts: list[float] = []
            any_down = False
            any_degraded = False
            for n in region_nodes:
                url = n["url"]
                last = latest.get(url)
                agg = aggs_24h.get(url, {})
                agg7 = aggs_7d.get(url, {})
                if last is None:
                    node_rows.append({
                        "url": url, "status": "unknown", "score": None,
                        "latency_ms": None, "uptime_pct_24h": None, "uptime_pct_7d": None,
                    })
                    continue
                # Score a single node using the same path /status does.
                recent = database.get_recent_measurements(url, limit=20, db_path=db_path_key)
                breakdown = scoring.calculate_score(
                    recent, reference_block=ref,
                    current_ok=bool(last["success"]),
                    current_latency_ms=last.get("latency_ms"),
                    current_block_height=last.get("block_height"),
                )
                status_label = scoring.status_label(breakdown.score, bool(last["success"]))
                if status_label == "down": any_down = True
                elif status_label in ("warning", "critical"): any_degraded = True
                if agg.get("avg_latency_ms") is not None:
                    avg_latency_samples.append(agg["avg_latency_ms"])
                if agg.get("uptime_pct") is not None:
                    uptime_pcts.append(agg["uptime_pct"])
                node_rows.append({
                    "url": url,
                    "status": status_label,
                    "score": breakdown.score,
                    "latency_ms": last.get("latency_ms"),
                    "uptime_pct_24h": agg.get("uptime_pct"),
                    "uptime_pct_7d": agg7.get("uptime_pct"),
                })
            region_status = "down" if any_down else ("warning" if any_degraded else "ok")
            if all(r["status"] == "unknown" for r in node_rows):
                region_status = "unknown"
            out.append({
                "region": region,
                "label": geo.get("label") or region,
                "lat": geo.get("lat"),
                "lng": geo.get("lng"),
                "node_count": len(region_nodes),
                "status": region_status,
                "avg_latency_ms": round(sum(avg_latency_samples) / len(avg_latency_samples), 1) if avg_latency_samples else None,
                "avg_uptime_pct_24h": round(sum(uptime_pcts) / len(uptime_pcts), 2) if uptime_pcts else None,
                "nodes": node_rows,
            })
        # Stable ordering: geographic regions first (by label), then
        # no-anchor regions at the end.
        out.sort(key=lambda r: (r["lat"] is None, r["label"]))
        return {"regions": out}

    @app.get("/api/v1/regions")
    def regions() -> dict:
        """Regional aggregates for the map and the aggregate table."""
        data = _regions_aggregate(str(database.DB_PATH))
        return {
            "generated_at": _utcnow_iso(),
            **data,
        }

    @app.get("/api/v1/stats/chain-availability")
    def stats_chain_availability(range: str = Query("24h", pattern="^(24h|7d)$")) -> dict:
        """Fleet-wide up/down counts bucketed over time.

        24 h window uses 10-minute buckets (144 points). 7 d window uses
        60-minute buckets (168 points). Both stay comfortably under the
        `maxTicksLimit` Chart.js renders on a time axis."""
        minutes = _range_minutes(range)
        bucket_seconds = 600 if range == "24h" else 3600
        points = _chain_availability(minutes, bucket_seconds, str(database.DB_PATH))
        return {
            "range": range,
            "bucket_seconds": bucket_seconds,
            "generated_at": _utcnow_iso(),
            "points": points,
        }

    @app.get("/api/v1/stats/daily-comparison")
    def stats_daily_comparison() -> dict:
        """Per-node today / yesterday / same slice last week."""
        data = _daily_comparison(str(database.DB_PATH))
        return {
            "generated_at": _utcnow_iso(),
            **data,
        }

    # ------------------------------------------------------------------ #
    #  Phase 6 Etappe 8 — community ingest, admin, sources.              #
    # ------------------------------------------------------------------ #
    # Ingest accepts batched measurements from external participants;
    # admin manages those participants; /sources surfaces them in the
    # dashboard. All three live here so build_app() owns the rate-limiter
    # state (analogous to how it owns the ttl_caches above).

    rate_limiter = ingest_mod.RateLimiter()

    def _require_admin(authorization: Optional[str]) -> None:
        """Validate the Bearer admin token. Fail-closed when unset."""
        expected = config.ADMIN_TOKEN
        if not expected:
            # Fail closed: a build deployed without the env var must
            # not silently accept admin commands. 503 (rather than 401)
            # signals "this surface is not configured", not "wrong key".
            raise HTTPException(status_code=503, detail="admin disabled — STEEMAPPS_ADMIN_TOKEN not set")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization[len("Bearer "):]
        # compare_digest is constant-time; protects against the trivial
        # "compare and short-circuit" timing leak in `==`.
        if not secrets.compare_digest(token, expected):
            raise HTTPException(status_code=401, detail="invalid admin token")

    @app.post("/api/v1/ingest")
    def ingest_measurements(
        body: IngestRequest,
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ) -> dict:
        """Batched ingest of community-contributed measurements."""
        if not x_api_key:
            raise HTTPException(status_code=401, detail="missing X-API-Key header")
        participant = participants_mod.verify_api_key(x_api_key, db_path=database.DB_PATH)
        if participant is None:
            # Same response regardless of "no row" / "wrong hash" /
            # "deactivated" — see participants.verify_api_key for why.
            raise HTTPException(status_code=401, detail="invalid or inactive api key")

        granted, remaining = rate_limiter.consume(str(participant.id), len(body.measurements))
        if not granted:
            raise HTTPException(
                status_code=429,
                detail=f"rate limit exceeded — {int(remaining)} tokens remaining; cap {ingest_mod.RATE_LIMIT_PER_HOUR}/h",
            )

        known_nodes = {n["url"] for n in config.load_nodes()}
        accepted = 0
        rejected: list[dict] = []
        now = datetime.now(timezone.utc)

        for i, m in enumerate(body.measurements):
            row = m.model_dump()
            reason = ingest_mod.validate_row(row, known_nodes=known_nodes, now=now)
            if reason:
                rejected.append({"index": i, "reason": reason})
                continue
            ts = ingest_mod.normalise_timestamp(row["timestamp"])
            database.insert_measurement(
                database.Measurement(
                    timestamp=ts,
                    node_url=row["node_url"],
                    success=bool(row["success"]),
                    latency_ms=row.get("latency_ms"),
                    block_height=row.get("block_height"),
                    error_message=row.get("error_category"),
                    source_location=participant.display_label,
                ),
                database.DB_PATH,
            )
            accepted += 1

        return {
            "accepted": accepted,
            "rejected": rejected,
            "rate_limit_remaining": int(remaining),
        }

    @app.post("/api/v1/admin/participants", status_code=201)
    def admin_create_participant(
        body: ParticipantCreate,
        authorization: Optional[str] = Header(default=None),
    ) -> dict:
        """Register a new participant. Returns the plaintext API key once."""
        _require_admin(authorization)
        try:
            participant, plain_key = participants_mod.create_participant(
                steem_account=body.steem_account,
                display_label=body.display_label,
                region=body.region,
                note=body.note,
                db_path=database.DB_PATH,
            )
        except Exception as e:
            # The UNIQUE constraint on steem_account raises IntegrityError
            # when the same account is enrolled twice; we surface that as
            # 409 so the operator can re-use the existing key instead of
            # silently creating duplicates.
            if "UNIQUE" in str(e):
                raise HTTPException(status_code=409, detail=f"steem_account already registered: {body.steem_account}")
            raise
        return {
            "id": participant.id,
            "steem_account": participant.steem_account,
            "display_label": participant.display_label,
            "region": participant.region,
            "created_at": participant.created_at,
            "active": participant.active,
            "api_key": plain_key,
            "warning": "Store this API key now — it will not be shown again.",
        }

    @app.get("/api/v1/admin/participants")
    def admin_list_participants(
        authorization: Optional[str] = Header(default=None),
    ) -> dict:
        _require_admin(authorization)
        rows = participants_mod.list_participants(db_path=database.DB_PATH)
        return {
            "participants": [
                {
                    "id": p.id,
                    "steem_account": p.steem_account,
                    "display_label": p.display_label,
                    "region": p.region,
                    "created_at": p.created_at,
                    "active": p.active,
                    "note": p.note,
                }
                for p in rows
            ],
        }

    @app.patch("/api/v1/admin/participants/{participant_id}")
    def admin_patch_participant(
        participant_id: int,
        body: ParticipantPatch,
        authorization: Optional[str] = Header(default=None),
    ) -> dict:
        _require_admin(authorization)
        existing = participants_mod.get_participant(participant_id, db_path=database.DB_PATH)
        if existing is None:
            raise HTTPException(status_code=404, detail="participant not found")
        updated = existing
        if body.active is not None:
            updated = participants_mod.set_active(participant_id, body.active, db_path=database.DB_PATH) or existing
        if body.note is not None:
            with database.connect(database.DB_PATH) as conn:
                conn.execute("UPDATE participants SET note=? WHERE id=?", (body.note, participant_id))
            updated = participants_mod.get_participant(participant_id, db_path=database.DB_PATH) or updated
        return {
            "id": updated.id,
            "steem_account": updated.steem_account,
            "display_label": updated.display_label,
            "region": updated.region,
            "active": updated.active,
            "note": updated.note,
        }

    @app.delete("/api/v1/admin/participants/{participant_id}", status_code=200)
    def admin_delete_participant(
        participant_id: int,
        authorization: Optional[str] = Header(default=None),
    ) -> dict:
        _require_admin(authorization)
        deleted = participants_mod.delete_participant(participant_id, db_path=database.DB_PATH)
        if not deleted:
            raise HTTPException(status_code=404, detail="participant not found")
        return {"deleted": True, "id": participant_id}

    @app.get("/api/v1/sources/locations")
    def sources_locations() -> dict:
        """Geo-decorated list of active measurement sources.

        Powers the lime-coloured markers on the regions map. Mirrors
        /api/v1/sources but adds (lat, lng, region_label) per source
        from config.REGION_COORDINATES — a region without an anchor
        ("global", "unknown") returns lat=lng=null and the frontend
        skips it on the map (it still appears in the Sources table).
        """
        parts = participants_mod.list_participants(db_path=database.DB_PATH)
        counts = participants_mod.measurement_counts(db_path=database.DB_PATH)
        primary = config.PRIMARY_SOURCE
        primary_counts = counts.get(primary["label"], {"h24": 0, "h7d": 0, "last_seen": None})

        def _decorate(*, id, primary_flag, steem_account, display_label, region, h24, last_seen):
            geo = config.REGION_COORDINATES.get(region or "", {})
            return {
                "id": id,
                "primary": primary_flag,
                "steem_account": steem_account,
                "display_label": display_label,
                "region": region,
                "region_label": geo.get("label") or region,
                "lat": geo.get("lat"),
                "lng": geo.get("lng"),
                "measurements_24h": h24,
                "last_seen": last_seen,
            }

        out = [_decorate(
            id=0,
            primary_flag=True,
            steem_account=primary["steem_account"],
            display_label=primary["display_label"],
            region=primary["region"],
            h24=primary_counts["h24"],
            last_seen=primary_counts["last_seen"],
        )]
        for p in parts:
            if not p.active:
                continue
            c = counts.get(p.display_label, {"h24": 0, "h7d": 0, "last_seen": None})
            out.append(_decorate(
                id=p.id,
                primary_flag=False,
                steem_account=p.steem_account,
                display_label=p.display_label,
                region=p.region,
                h24=c["h24"],
                last_seen=c["last_seen"],
            ))
        return {
            "generated_at": _utcnow_iso(),
            "sources": out,
        }

    @app.get("/api/v1/sources")
    def sources_list() -> dict:
        """Public list of measurement sources for the dashboard.

        Always includes the primary monitor (config.PRIMARY_SOURCE) plus
        every active participant. Inactive participants are hidden so a
        deactivated key vanishes from the attribution footer immediately."""
        parts = participants_mod.list_participants(db_path=database.DB_PATH)
        counts = participants_mod.measurement_counts(db_path=database.DB_PATH)
        primary = config.PRIMARY_SOURCE
        primary_counts = counts.get(primary["label"], {"h24": 0, "h7d": 0, "last_seen": None})
        sources = [{
            "id": 0,
            "primary": True,
            "steem_account": primary["steem_account"],
            "display_label": primary["display_label"],
            "region": primary["region"],
            "active": True,
            "measurements_24h": primary_counts["h24"],
            "measurements_7d": primary_counts["h7d"],
            "last_seen": primary_counts["last_seen"],
        }]
        for p in parts:
            if not p.active:
                continue
            c = counts.get(p.display_label, {"h24": 0, "h7d": 0, "last_seen": None})
            sources.append({
                "id": p.id,
                "primary": False,
                "steem_account": p.steem_account,
                "display_label": p.display_label,
                "region": p.region,
                "active": True,
                "created_at": p.created_at,
                "measurements_24h": c["h24"],
                "measurements_7d": c["h7d"],
                "last_seen": c["last_seen"],
            })
        return {
            "generated_at": _utcnow_iso(),
            "sources": sources,
        }

    @app.get("/api/v1/nodes")
    def nodes_list() -> dict:
        """Lean URL+region list. Used by the participant script at startup
        so the operator does not have to hand-maintain the node list."""
        nodes = config.load_nodes()
        return {
            "generated_at": _utcnow_iso(),
            "nodes": [{"url": n["url"], "region": n.get("region")} for n in nodes],
        }

    # ------------------------------------------------------------------ #
    #  Self-service onboarding (/join/*).                                 #
    # ------------------------------------------------------------------ #
    # Single-step flow: applicant submits account+label+region; we verify
    # the account exists on-chain and issue an API key in one response.
    # No memo verification, no pending state. Operator moderation lives
    # in /api/v1/admin/participants if a label needs cleanup.

    def _raise_join(err: join_mod.JoinError):
        raise HTTPException(
            status_code=err.status_code,
            detail={"code": err.code, "message": err.message},
        )

    @app.get("/api/v1/join/regions")
    def join_regions() -> dict:
        """Region dropdown options for the join form."""
        return {"regions": join_mod.allowed_regions()}

    @app.post("/api/v1/join/register", status_code=201)
    def join_register(body: JoinRegisterRequest) -> dict:
        try:
            reg = join_mod.register_participant(
                steem_account=body.steem_account,
                display_label=body.display_label,
                region=body.region,
                db_path=database.DB_PATH,
            )
        except join_mod.JoinError as e:
            _raise_join(e)
        p = reg.participant
        return {
            "api_key": reg.api_key,
            "steem_account": p.steem_account,
            "display_label": p.display_label,
            "region": p.region,
            "warning": "Store this key now — it cannot be retrieved again.",
        }

    return app


# Let uvicorn import `api:app` without needing to call build_app() ourselves.
app = build_app()
