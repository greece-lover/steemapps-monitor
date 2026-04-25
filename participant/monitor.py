#!/usr/bin/env python3
"""Community participant monitor — measure Steem nodes, batch, ship.

Designed to be tiny and auditable: <200 lines, one external dep (httpx),
no global state beyond the in-memory buffer. Run via Docker, systemd,
or `python monitor.py` from a venv. Reads its API key and the ingest
endpoint URL from environment variables — never hard-codes a secret.

Lifecycle:
    1. Boot:   fetch the node list from /api/v1/nodes once.
    2. Tick:   every POLL_INTERVAL_S seconds, probe every node in parallel
               and append the result to an in-memory buffer.
    3. Flush:  every FLUSH_INTERVAL_S seconds, POST the buffer to /ingest.
               On HTTP failure, keep the rows and retry on the next flush.
               On 401 / 403, log loudly and stop — the operator must
               re-issue a key.

The script intentionally does not persist its buffer to disk: a restart
loses at most FLUSH_INTERVAL_S of data, which is the right trade-off
against introducing a write-path that needs cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

# -----------------------------------------------------------------
#  Config — environment-only, no defaults for the secret.
# -----------------------------------------------------------------

API_BASE = os.environ.get("STEEMAPPS_API_BASE", "https://api.steemapps.com").rstrip("/")
API_KEY = os.environ.get("STEEMAPPS_API_KEY")
LABEL = os.environ.get("STEEMAPPS_LABEL", "participant")  # cosmetic only — server uses display_label
POLL_INTERVAL_S = int(os.environ.get("STEEMAPPS_POLL_INTERVAL_S", "60"))
FLUSH_INTERVAL_S = int(os.environ.get("STEEMAPPS_FLUSH_INTERVAL_S", "300"))
REQUEST_TIMEOUT_S = float(os.environ.get("STEEMAPPS_TIMEOUT_S", "8.0"))
PROBE_METHOD = "condenser_api.get_dynamic_global_properties"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("participant")

_buffer: list[dict] = []
_buffer_lock = asyncio.Lock()
_shutdown = asyncio.Event()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# -----------------------------------------------------------------
#  Probe — same JSON-RPC call the central monitor uses.
# -----------------------------------------------------------------

async def probe_one(client: httpx.AsyncClient, url: str) -> dict:
    """Return one measurement dict, ready to ship."""
    started = time.perf_counter()
    payload = {"jsonrpc": "2.0", "method": PROBE_METHOD, "params": [], "id": 1}
    try:
        r = await client.post(url, json=payload, timeout=REQUEST_TIMEOUT_S)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if r.status_code != 200:
            return {
                "timestamp": _utcnow_iso(),
                "node_url": url,
                "success": False,
                "latency_ms": elapsed_ms,
                "block_height": None,
                "error_category": f"http_{r.status_code}",
            }
        body = r.json()
        height = body.get("result", {}).get("head_block_number")
        return {
            "timestamp": _utcnow_iso(),
            "node_url": url,
            "success": height is not None,
            "latency_ms": elapsed_ms,
            "block_height": int(height) if height is not None else None,
            "error_category": None if height is not None else "no_head_block",
        }
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        category = "timeout" if isinstance(e, httpx.TimeoutException) else "connect_error"
        return {
            "timestamp": _utcnow_iso(),
            "node_url": url,
            "success": False,
            "latency_ms": elapsed_ms,
            "block_height": None,
            "error_category": category,
        }
    except Exception as e:  # pragma: no cover — defensive catch-all
        return {
            "timestamp": _utcnow_iso(),
            "node_url": url,
            "success": False,
            "latency_ms": None,
            "block_height": None,
            "error_category": f"exception_{type(e).__name__}",
        }


async def fetch_nodes() -> list[str]:
    """Bootstrap the URL list from the central API."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
        r = await client.get(f"{API_BASE}/api/v1/nodes")
        r.raise_for_status()
        return [n["url"] for n in r.json()["nodes"]]


# -----------------------------------------------------------------
#  Loops — poll and flush run concurrently.
# -----------------------------------------------------------------

async def poll_loop(node_urls: list[str]) -> None:
    async with httpx.AsyncClient() as client:
        while not _shutdown.is_set():
            cycle_started = time.perf_counter()
            measurements = await asyncio.gather(*(probe_one(client, u) for u in node_urls))
            async with _buffer_lock:
                _buffer.extend(measurements)
            elapsed = time.perf_counter() - cycle_started
            sleep_for = max(1.0, POLL_INTERVAL_S - elapsed)
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass


async def flush_loop() -> None:
    async with httpx.AsyncClient() as client:
        while not _shutdown.is_set():
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=FLUSH_INTERVAL_S)
                # Shutdown fired — flush one last time before returning.
            except asyncio.TimeoutError:
                pass
            await flush_once(client)
            if _shutdown.is_set():
                return


async def flush_once(client: httpx.AsyncClient) -> None:
    async with _buffer_lock:
        if not _buffer:
            return
        batch = _buffer.copy()
        _buffer.clear()
    try:
        r = await client.post(
            f"{API_BASE}/api/v1/ingest",
            json={"measurements": batch},
            headers={"X-API-Key": API_KEY or ""},
            timeout=REQUEST_TIMEOUT_S * 2,
        )
        if r.status_code in (401, 403):
            log.error("API rejected key (HTTP %s) — stopping. Re-issue your key with the operator.", r.status_code)
            _shutdown.set()
            return
        if r.status_code == 429:
            log.warning("Rate-limited (HTTP 429). Dropping batch of %d to stay within budget.", len(batch))
            return
        if r.status_code >= 400:
            # Network blip or server-side error — re-queue and try again
            # at the next flush. Keep the buffer bounded so a long outage
            # doesn't OOM the box.
            log.warning("Ingest HTTP %s — re-queueing batch of %d.", r.status_code, len(batch))
            async with _buffer_lock:
                _buffer[:0] = batch[-1000:]
            return
        body = r.json()
        log.info(
            "Flushed %d (accepted=%d, rejected=%d, remaining=%s)",
            len(batch), body.get("accepted", 0), len(body.get("rejected", [])),
            body.get("rate_limit_remaining"),
        )
    except (httpx.TimeoutException, httpx.ConnectError) as e:
        log.warning("Ingest network error (%s) — re-queueing batch.", type(e).__name__)
        async with _buffer_lock:
            _buffer[:0] = batch[-1000:]


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    if sys.platform == "win32":
        return  # signals on Windows are limited; Ctrl+C still raises KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown.set)


async def main() -> int:
    if not API_KEY:
        log.error("STEEMAPPS_API_KEY is not set. Refusing to start.")
        return 2
    log.info("Participant boot — label=%s, target=%s, poll=%ds, flush=%ds",
             LABEL, API_BASE, POLL_INTERVAL_S, FLUSH_INTERVAL_S)
    try:
        urls = await fetch_nodes()
    except Exception as e:
        log.error("Failed to fetch node list from %s: %s", API_BASE, e)
        return 3
    log.info("Got %d nodes from %s.", len(urls), API_BASE)
    _install_signal_handlers(asyncio.get_running_loop())
    await asyncio.gather(poll_loop(urls), flush_loop())
    log.info("Shutdown complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
