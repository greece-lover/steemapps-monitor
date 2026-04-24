"""Central configuration — loaded once at process start.

All paths are resolved relative to this file so the same module works whether
the process is invoked as `python monitor.py`, `python -m ...`, or via the
systemd unit.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
LOG_DIR = HERE / "logs"
NODES_FILE = HERE / "nodes.json"
DB_PATH = DATA_DIR / "measurements.sqlite"

# How often the poller issues one JSON-RPC call to every configured node.
POLL_INTERVAL_S: int = 60

# Per-request timeout (connect + read) for the JSON-RPC call. The
# MEASUREMENT-METHODOLOGY document pins this at 8 s — anything slower is
# treated as unusable from a frontend's perspective.
REQUEST_TIMEOUT_S: float = 8.0

# The JSON-RPC method used as our liveness probe.
PROBE_METHOD: str = "condenser_api.get_dynamic_global_properties"

# FastAPI / uvicorn binding. Loopback-only; a reverse proxy exposes the API
# publicly on the production host. Port is overridable via env so a
# second instance (e.g. the production monitor next to the dev VM) can
# coexist with the default.
API_HOST: str = "127.0.0.1"
API_PORT: int = int(os.environ.get("STEEMAPPS_API_PORT", "8110"))

# Methodology version recorded in every API response — see
# docs/MEASUREMENT-METHODOLOGY.md.
METHODOLOGY_VERSION: str = "mv1"

# Identifier for this monitor instance. Once multi-location monitoring comes
# online (Phase 5+), each measurement row carries this so we can tell which
# observer saw what. Override via env var when running a second instance.
SOURCE_LOCATION: str = os.environ.get("STEEMAPPS_SOURCE_LOCATION", "contabo-de-1")


# Approximate geographic centres for each region name used in nodes.json,
# used by the /api/v1/regions endpoint and the regions.html map. Regions
# without a real-world anchor (global / unknown) have `lat`=None — the
# map skips them and the aggregate table still includes them.
REGION_COORDINATES: dict[str, dict] = {
    "us-east":    {"lat": 40.71,  "lng":  -74.01, "label": "US East"},
    "us-west":    {"lat": 37.77,  "lng": -122.42, "label": "US West"},
    "us-central": {"lat": 32.78,  "lng":  -96.80, "label": "US Central"},
    "asia":       {"lat":  1.35,  "lng":  103.82, "label": "Asia"},
    "eu-central": {"lat": 50.11,  "lng":    8.68, "label": "Europe Central"},
    "global":     {"lat":  None,  "lng":    None, "label": "Global / CDN"},
    "unknown":    {"lat":  None,  "lng":    None, "label": "Unknown"},
}


def load_nodes() -> list[dict]:
    """Read the node list from nodes.json.

    The file is the single source of truth — changing it and restarting the
    service is enough to add or remove a node. The DB `nodes` table is kept
    in sync on startup.
    """
    with NODES_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not all("url" in n for n in data):
        raise ValueError("nodes.json must be a list of objects with a 'url' field")
    return data
