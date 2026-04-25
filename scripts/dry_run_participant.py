"""End-to-end dry-run: register a mock participant, push a batch, verify.

Stays inside the test process — no real network, no real Steem nodes.
The point is to prove the wire format the participant script produces is
exactly what /api/v1/ingest accepts, and to give the deployment a smoke
test we can rerun whenever the contract changes.

Run from the repo root:
    .venv/bin/python scripts/dry_run_participant.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Add parent (repo root) to sys.path so participant/monitor.py imports
# the way it would when installed.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

import config
import database
import participants as participants_mod
from api import build_app


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    # 1. Throwaway DB + nodes file.
    tmp = Path(tempfile.mkdtemp(prefix="steemapps-dryrun-"))
    db_path = tmp / "dryrun.sqlite"
    nodes_file = tmp / "nodes.json"
    nodes_file.write_text(json.dumps([
        {"url": "https://api.steemit.com",         "region": "us-east"},
        {"url": "https://api.justyy.com",          "region": "us-west"},
        {"url": "https://steemd.steemworld.org",   "region": "eu-central"},
    ]))
    database.initialise(db_path)
    config.NODES_FILE = nodes_file
    database.DB_PATH = db_path
    config.ADMIN_TOKEN = "dry-run-admin"

    print(f"[1/5] Throwaway DB at {db_path}")

    # 2. Register a mock participant via the admin route.
    app = build_app()
    client = TestClient(app)

    r = client.post(
        "/api/v1/admin/participants",
        json={"steem_account": "mock-tester", "display_label": "Mock (TEST)", "region": "us-east"},
        headers={"Authorization": "Bearer dry-run-admin"},
    )
    assert r.status_code == 201, r.text
    api_key = r.json()["api_key"]
    print(f"[2/5] Participant registered, API key = {api_key[:12]}…")

    # 3. Build a measurement batch the way participant/monitor.py would.
    now = datetime.now(timezone.utc)
    batch = {
        "measurements": [
            {
                "timestamp": _iso(now),
                "node_url": "https://api.steemit.com",
                "success": True,
                "latency_ms": 234,
                "block_height": 105_500_000,
                "error_category": None,
            },
            {
                "timestamp": _iso(now),
                "node_url": "https://api.justyy.com",
                "success": True,
                "latency_ms": 412,
                "block_height": 105_500_000,
                "error_category": None,
            },
            {
                "timestamp": _iso(now),
                "node_url": "https://steemd.steemworld.org",
                "success": False,
                "latency_ms": 8001,
                "block_height": None,
                "error_category": "timeout",
            },
        ]
    }
    print(f"[3/5] Built batch with {len(batch['measurements'])} measurements")

    # 4. POST through the same FastAPI app the participant would hit.
    r = client.post("/api/v1/ingest", json=batch, headers={"X-API-Key": api_key})
    assert r.status_code == 200, r.text
    body = r.json()
    print(f"[4/5] Ingest response: accepted={body['accepted']}, rejected={len(body['rejected'])}, "
          f"remaining={body['rate_limit_remaining']}")
    assert body["accepted"] == 3
    assert body["rejected"] == []

    # 5. Read back what landed in the DB; the source_location must match
    #    the participant's display_label, not "test" or anything else.
    rows = database.get_recent_measurements(limit=10, db_path=db_path)
    assert len(rows) == 3, f"expected 3 rows, got {len(rows)}"
    assert all(r["source_location"] == "Mock (TEST)" for r in rows)
    print(f"[5/5] DB now contains {len(rows)} rows, all attributed to 'Mock (TEST)'.")

    # And /sources lists the mock participant with the right counts.
    sr = client.get("/api/v1/sources")
    assert sr.status_code == 200
    mock = next(s for s in sr.json()["sources"] if s["steem_account"] == "mock-tester")
    print(f"      /sources reports {mock['measurements_24h']} 24h, {mock['measurements_7d']} 7d for mock-tester.")
    assert mock["measurements_24h"] == 3

    print("\nDRY RUN OK — ingest pipeline contract is intact end-to-end.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
