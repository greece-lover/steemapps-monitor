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

    return app


# Let uvicorn import `api:app` without needing to call build_app() ourselves.
app = build_app()
