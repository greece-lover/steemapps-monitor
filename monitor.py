"""Monitor entry point.

Runs two asyncio tasks in one process:

1. `poll_loop` — every POLL_INTERVAL_S, issue one JSON-RPC call to each
   configured node and persist the outcome.
2. `uvicorn.Server.serve` — the FastAPI app from api.py, bound to the
   loopback-only address configured in config.py.

Sharing one event loop means the API always sees the DB state the poller
just wrote, and we pay for only one Python interpreter on the VM.
"""

from __future__ import annotations

import asyncio
import signal
import time
from datetime import datetime, timezone

import httpx
import uvicorn

import config
import database
import logger as logger_mod
from api import build_app


log = logger_mod.get("monitor")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def probe_node(client: httpx.AsyncClient, url: str) -> database.Measurement:
    """Issue one JSON-RPC call and return the resulting Measurement row."""
    payload = {
        "jsonrpc": "2.0",
        "method": config.PROBE_METHOD,
        "params": [],
        "id": 1,
    }
    t0 = time.perf_counter()
    timestamp = _utcnow_iso()
    try:
        resp = await client.post(url, json=payload, timeout=config.REQUEST_TIMEOUT_S)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code != 200:
            return database.Measurement(
                timestamp=timestamp, node_url=url,
                success=False, latency_ms=latency_ms,
                block_height=None,
                error_message=f"HTTP {resp.status_code}",
                source_location=config.SOURCE_LOCATION,
            )
        try:
            body = resp.json()
        except Exception as exc:
            return database.Measurement(
                timestamp=timestamp, node_url=url,
                success=False, latency_ms=latency_ms,
                block_height=None,
                error_message=f"body_invalid: {exc}",
                source_location=config.SOURCE_LOCATION,
            )
        if "error" in body:
            return database.Measurement(
                timestamp=timestamp, node_url=url,
                success=False, latency_ms=latency_ms,
                block_height=None,
                error_message=f"rpc_error: {body['error']}",
                source_location=config.SOURCE_LOCATION,
            )
        head_block = (body.get("result") or {}).get("head_block_number")
        if not isinstance(head_block, int):
            return database.Measurement(
                timestamp=timestamp, node_url=url,
                success=False, latency_ms=latency_ms,
                block_height=None,
                error_message="body_stale: head_block_number missing",
                source_location=config.SOURCE_LOCATION,
            )
        return database.Measurement(
            timestamp=timestamp, node_url=url,
            success=True, latency_ms=latency_ms,
            block_height=head_block, error_message=None,
            source_location=config.SOURCE_LOCATION,
        )
    except httpx.TimeoutException:
        return database.Measurement(
            timestamp=timestamp, node_url=url,
            success=False, latency_ms=None, block_height=None,
            error_message="timeout",
            source_location=config.SOURCE_LOCATION,
        )
    except httpx.ConnectError as exc:
        return database.Measurement(
            timestamp=timestamp, node_url=url,
            success=False, latency_ms=None, block_height=None,
            error_message=f"connect_error: {exc}",
            source_location=config.SOURCE_LOCATION,
        )
    except Exception as exc:
        return database.Measurement(
            timestamp=timestamp, node_url=url,
            success=False, latency_ms=None, block_height=None,
            error_message=f"unexpected: {type(exc).__name__}: {exc}",
            source_location=config.SOURCE_LOCATION,
        )


async def run_tick(client: httpx.AsyncClient, nodes: list[dict]) -> None:
    """Probe every node once, concurrently, and write the results."""
    results = await asyncio.gather(*(probe_node(client, n["url"]) for n in nodes))
    for m in results:
        database.insert_measurement(m)
    ok = sum(1 for m in results if m.success)
    log.info("tick done: %d/%d ok", ok, len(results))


async def poll_loop(stop: asyncio.Event) -> None:
    """Main poller — runs until `stop` is set."""
    nodes = config.load_nodes()
    database.initialise()
    database.sync_nodes(nodes)
    log.info("poll loop starting for %d nodes, interval=%ds",
             len(nodes), config.POLL_INTERVAL_S)

    # One HTTP client for the lifetime of the loop — connection pooling,
    # keep-alive, the works.
    limits = httpx.Limits(max_connections=max(4, len(nodes) * 2))
    async with httpx.AsyncClient(limits=limits,
                                 headers={"User-Agent": "steemapps-monitor/0.1"}) as client:
        # Fire an immediate first tick on boot so the API has data without
        # waiting a full minute.
        try:
            await run_tick(client, nodes)
        except Exception:
            log.exception("first tick failed")

        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=config.POLL_INTERVAL_S)
                # If we get here, stop was set during the sleep.
                break
            except asyncio.TimeoutError:
                pass
            try:
                await run_tick(client, nodes)
            except Exception:
                log.exception("tick failed; will retry next interval")


async def _serve_api(stop: asyncio.Event) -> None:
    app = build_app()
    cfg = uvicorn.Config(
        app,
        host=config.API_HOST,
        port=config.API_PORT,
        log_level="info",
        access_log=False,
        loop="asyncio",
    )
    server = uvicorn.Server(cfg)
    # Run uvicorn, but make sure we stop it when the poller asks us to.
    serve_task = asyncio.create_task(server.serve())
    await stop.wait()
    server.should_exit = True
    await serve_task


async def amain() -> None:
    logger_mod.setup()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal():
        log.info("shutdown signal received")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal)
        except NotImplementedError:
            # Windows asyncio doesn't support add_signal_handler; fall back
            # to the default KeyboardInterrupt path for dev runs.
            pass

    await asyncio.gather(poll_loop(stop), _serve_api(stop))


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
