"""Manual smoke test: one full probe cycle against the real Steem API nodes.

Run locally before deploying:
    .venv/Scripts/python tests/smoke_one_tick.py

Prints the outcome for each node. Not part of the automated pytest suite —
hitting the live network from CI would be flaky.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

import config  # noqa: E402
from monitor import probe_node  # noqa: E402


async def main() -> int:
    nodes = config.load_nodes()
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(probe_node(client, n["url"]) for n in nodes))
    for m in results:
        print(f"{m.node_url:30s} ok={m.success}  lat={m.latency_ms}ms  "
              f"block={m.block_height}  err={m.error_message}")
    return 0 if all(m.success for m in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
