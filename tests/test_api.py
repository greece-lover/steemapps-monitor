"""API endpoint tests.

Uses FastAPI's TestClient (starlette-based) which hits the ASGI app in-process,
so no uvicorn server is required. The app depends on `config.load_nodes()`
and `database.DB_PATH`; both are monkey-patched per test to point at a
throw-away SQLite file and a synthetic two-node list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import database
from api import build_app
from database import Measurement, initialise, insert_measurement


NODE_A = "https://a.example"
NODE_B = "https://b.example"


@pytest.fixture
def app_and_db(tmp_path: Path, monkeypatch):
    """Build a fresh FastAPI app bound to a throw-away database."""
    db_path = tmp_path / "api-test.sqlite"
    initialise(db_path)

    # Point every code path that reads DB_PATH at the temp file. The modules
    # read the constant at call time, so patching the attribute is enough.
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(config, "NODES_FILE", tmp_path / "nodes.json")

    (tmp_path / "nodes.json").write_text(json.dumps([
        {"url": NODE_A, "region": "eu"},
        {"url": NODE_B, "region": "us"},
    ]))

    app = build_app()
    return TestClient(app), db_path


def _insert(db_path: Path, ts: str, url: str, ok: bool, latency: int | None = 200,
            height: int | None = 1000) -> None:
    insert_measurement(
        Measurement(
            timestamp=ts, node_url=url, success=ok,
            latency_ms=latency, block_height=height,
            error_message=None if ok else "timeout",
            source_location="test",
        ),
        db_path,
    )


def test_health_returns_ok_and_methodology_version(app_and_db):
    client, _ = app_and_db
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "steemapps-monitor"
    assert body["status"] == "ok"
    assert body["methodology_version"] == "mv1"
    assert "now" in body


def test_status_with_no_data_returns_unknown_for_every_configured_node(app_and_db):
    client, _ = app_and_db
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    urls = {n["url"]: n for n in body["nodes"]}
    assert set(urls) == {NODE_A, NODE_B}
    for n in body["nodes"]:
        assert n["status"] == "unknown"
        assert n["score"] is None


def test_status_computes_scores_from_inserted_rows(app_and_db):
    client, db = app_and_db
    # One healthy node, one that responded slowly enough to be degraded.
    _insert(db, "2026-04-24T10:00:00Z", NODE_A, ok=True, latency=200, height=1000)
    _insert(db, "2026-04-24T10:00:00Z", NODE_B, ok=True, latency=3000, height=1000)
    r = client.get("/api/v1/status")
    nodes = {n["url"]: n for n in r.json()["nodes"]}
    assert nodes[NODE_A]["score"] == 100
    assert nodes[NODE_A]["status"] == "ok"
    # Latency 3000 ms → −20 (>500) −50 (>2000) = 30.
    assert nodes[NODE_B]["score"] == 30
    assert nodes[NODE_B]["status"] == "down"
    # reference_block is the max head across successful nodes.
    assert r.json()["reference_block"] == 1000


def test_status_reports_block_lag_for_laggy_node(app_and_db):
    client, db = app_and_db
    _insert(db, "2026-04-24T10:00:00Z", NODE_A, ok=True, latency=200, height=1000)
    _insert(db, "2026-04-24T10:00:00Z", NODE_B, ok=True, latency=200, height=990)
    body = client.get("/api/v1/status").json()
    nodes = {n["url"]: n for n in body["nodes"]}
    assert nodes[NODE_A]["block_lag"] == 0
    assert nodes[NODE_B]["block_lag"] == 10


def test_history_returns_points_in_chronological_order(app_and_db):
    client, db = app_and_db
    _insert(db, "2026-04-24T10:00:00Z", NODE_A, ok=True, latency=100)
    _insert(db, "2026-04-24T10:01:00Z", NODE_A, ok=True, latency=110)
    _insert(db, "2026-04-24T10:02:00Z", NODE_A, ok=False, latency=None)
    r = client.get(f"/api/v1/nodes/{NODE_A}/history?hours=1")
    assert r.status_code == 200
    body = r.json()
    assert body["node_url"] == NODE_A
    assert body["hours"] == 1
    # Oldest first — Chart.js plots left-to-right.
    timestamps = [p["ts"] for p in body["points"]]
    assert timestamps == sorted(timestamps)
    # The lean sparkline shape: three fields, nothing else.
    assert set(body["points"][0].keys()) == {"ts", "latency_ms", "success"}
    # `success` is normalised to a boolean (SQLite stores 0/1).
    assert body["points"][-1]["success"] is False


def test_history_rejects_unknown_nodes_with_404(app_and_db):
    client, _ = app_and_db
    r = client.get("/api/v1/nodes/https://not-configured.example/history")
    assert r.status_code == 404


def test_history_rejects_out_of_range_hours(app_and_db):
    client, _ = app_and_db
    assert client.get(f"/api/v1/nodes/{NODE_A}/history?hours=0").status_code == 422
    assert client.get(f"/api/v1/nodes/{NODE_A}/history?hours=200").status_code == 422


def test_uptime_computes_percentage(app_and_db):
    client, db = app_and_db
    # 6 ok + 4 fail = 60 %.
    base = "2026-04-24T10:00:"
    for i in range(6):
        _insert(db, f"{base}{i:02d}Z", NODE_A, ok=True)
    for i in range(4):
        _insert(db, f"{base}{10 + i:02d}Z", NODE_A, ok=False)
    r = client.get(f"/api/v1/nodes/{NODE_A}/uptime?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 30
    assert body["total"] == 10
    assert body["ok"] == 6
    assert body["uptime_pct"] == 60.0


def test_uptime_rejects_unknown_nodes_with_404(app_and_db):
    client, _ = app_and_db
    r = client.get("/api/v1/nodes/https://not-configured.example/uptime")
    assert r.status_code == 404


def test_uptime_rejects_out_of_range_days(app_and_db):
    client, _ = app_and_db
    assert client.get(f"/api/v1/nodes/{NODE_A}/uptime?days=0").status_code == 422
    assert client.get(f"/api/v1/nodes/{NODE_A}/uptime?days=31").status_code == 422


def test_cors_headers_are_present(app_and_db):
    client, _ = app_and_db
    r = client.get("/api/v1/health", headers={"Origin": "https://dashboard.example"})
    assert r.headers.get("access-control-allow-origin") == "*"
