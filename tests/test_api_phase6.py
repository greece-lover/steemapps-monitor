"""Phase 6 API tests.

Covers /nodes/{url}/detail, /nodes/{url}/outages, /outages, /stats/top.
Reuses the pattern from test_api.py: a fresh FastAPI app against a
throw-away SQLite, each test gets its own cache because build_app()
defines the cached helpers inside itself.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
    db_path = tmp_path / "phase6-test.sqlite"
    initialise(db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(config, "NODES_FILE", tmp_path / "nodes.json")
    (tmp_path / "nodes.json").write_text(json.dumps([
        {"url": NODE_A, "region": "eu-central"},
        {"url": NODE_B, "region": "us-west"},
    ]))
    app = build_app()
    return TestClient(app), db_path


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _insert(db_path: Path, ts: datetime, url: str, ok: bool, latency: int | None = 200) -> None:
    insert_measurement(
        Measurement(
            timestamp=_iso(ts),
            node_url=url,
            success=ok,
            latency_ms=latency if ok else None,
            block_height=1000 if ok else None,
            error_message=None if ok else "timeout",
            source_location="test",
        ),
        db_path,
    )


# =============================================================================
#  /nodes/{url}/detail
# =============================================================================

def test_detail_returns_percentiles_for_successful_ticks(app_and_db):
    client, db = app_and_db
    now = datetime.now(timezone.utc)
    # Ten recent successful ticks with known latencies 100..1000 (step 100).
    for i, latency in enumerate([100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]):
        _insert(db, now - timedelta(minutes=9 - i), NODE_A, ok=True, latency=latency)

    r = client.get(f"/api/v1/nodes/{NODE_A}/detail?range=24h")
    assert r.status_code == 200
    body = r.json()
    stats = body["latency_stats"]
    assert stats["min"] == 100
    assert stats["max"] == 1000
    assert stats["avg"] == 550.0
    assert stats["sample_size"] == 10
    # Linear interpolation P50 on an even-length sorted list of
    # [100..1000] lands at 550.0.
    assert stats["p50"] == 550.0
    # P95 and P99 lie between the top two buckets.
    assert 900 <= stats["p95"] <= 1000
    assert 950 <= stats["p99"] <= 1000
    assert body["uptime"]["uptime_pct"] == 100.0
    assert body["outages_summary"]["total"] == 0


def test_detail_404_for_unknown_node(app_and_db):
    client, _ = app_and_db
    r = client.get("/api/v1/nodes/https%3A%2F%2Fghost.example/detail?range=24h")
    assert r.status_code == 404


def test_detail_rejects_invalid_range(app_and_db):
    client, _ = app_and_db
    r = client.get(f"/api/v1/nodes/{NODE_A}/detail?range=2d")
    assert r.status_code == 422


def test_detail_downsamples_when_over_1500_points(app_and_db):
    client, db = app_and_db
    # 2000 rows compressed to at most 1500 points.
    base = datetime.now(timezone.utc) - timedelta(hours=20)
    for i in range(2000):
        _insert(db, base + timedelta(seconds=i * 30), NODE_A, ok=True, latency=200 + i % 50)
    r = client.get(f"/api/v1/nodes/{NODE_A}/detail?range=24h")
    assert r.status_code == 200
    assert len(r.json()["points"]) <= 1500


# =============================================================================
#  Outage detection — per node and global
# =============================================================================

def test_outages_distinguish_short_from_real(app_and_db):
    client, db = app_and_db
    base = datetime.now(timezone.utc) - timedelta(hours=2)
    # Timeline (seconds from base):
    #   0..60   : ok       (one ok tick) — seeds the "healthy" prefix
    #   60..120 : fail     (one failing tick) — short outage (< 120 s)
    #   120..180: ok       — recovers
    #   180..480: fail × 5 — real outage (5 × 60 s = 300 s)
    #   480..540: ok       — recovers
    _insert(db, base + timedelta(seconds=0), NODE_A, ok=True)
    _insert(db, base + timedelta(seconds=60), NODE_A, ok=False)
    _insert(db, base + timedelta(seconds=120), NODE_A, ok=True)
    for i in range(5):
        _insert(db, base + timedelta(seconds=180 + i * 60), NODE_A, ok=False)
    _insert(db, base + timedelta(seconds=480), NODE_A, ok=True)

    r = client.get(f"/api/v1/nodes/{NODE_A}/outages?range=24h")
    assert r.status_code == 200
    body = r.json()
    assert body["severity_threshold_s"] == 120
    outages = body["outages"]
    severities = sorted(o["severity"] for o in outages)
    assert severities == ["real", "short"]
    # The real outage runs 180→480 = 300 s.
    real = next(o for o in outages if o["severity"] == "real")
    assert real["duration_s"] == 300
    short = next(o for o in outages if o["severity"] == "short")
    assert short["duration_s"] == 60


def test_outages_severity_filter(app_and_db):
    client, db = app_and_db
    base = datetime.now(timezone.utc) - timedelta(hours=2)
    _insert(db, base + timedelta(seconds=0), NODE_A, ok=True)
    _insert(db, base + timedelta(seconds=60), NODE_A, ok=False)  # short outage seed
    _insert(db, base + timedelta(seconds=120), NODE_A, ok=True)
    for i in range(5):
        _insert(db, base + timedelta(seconds=180 + i * 60), NODE_A, ok=False)
    _insert(db, base + timedelta(seconds=480), NODE_A, ok=True)

    r = client.get(f"/api/v1/nodes/{NODE_A}/outages?range=24h&severity=real")
    assert r.status_code == 200
    outages = r.json()["outages"]
    assert len(outages) == 1
    assert outages[0]["severity"] == "real"


def test_global_outages_filter_by_node(app_and_db):
    client, db = app_and_db
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    # Node A: one real outage (300 s).
    _insert(db, base + timedelta(seconds=0), NODE_A, ok=True)
    for i in range(5):
        _insert(db, base + timedelta(seconds=60 + i * 60), NODE_A, ok=False)
    _insert(db, base + timedelta(seconds=360), NODE_A, ok=True)
    # Node B: one short outage (60 s).
    _insert(db, base + timedelta(seconds=0), NODE_B, ok=True)
    _insert(db, base + timedelta(seconds=60), NODE_B, ok=False)
    _insert(db, base + timedelta(seconds=120), NODE_B, ok=True)

    r = client.get(f"/api/v1/outages?range=24h&node={NODE_A}")
    assert r.status_code == 200
    outages = r.json()["outages"]
    assert len(outages) == 1
    assert outages[0]["node_url"] == NODE_A
    assert outages[0]["severity"] == "real"


# =============================================================================
#  /stats/top — rankings
# =============================================================================

def test_stats_top_latency_sorts_ascending(app_and_db):
    client, db = app_and_db
    now = datetime.now(timezone.utc)
    # Node A avg ~100 ms, node B avg ~500 ms — A must rank first.
    for i in range(5):
        _insert(db, now - timedelta(minutes=i), NODE_A, ok=True, latency=100)
        _insert(db, now - timedelta(minutes=i), NODE_B, ok=True, latency=500)
    r = client.get("/api/v1/stats/top?metric=latency&range=24h&limit=2")
    assert r.status_code == 200
    ranked = r.json()["ranked"]
    assert [x["node_url"] for x in ranked] == [NODE_A, NODE_B]
    assert ranked[0]["avg_latency_ms"] <= ranked[1]["avg_latency_ms"]


def test_stats_top_uptime_sorts_descending(app_and_db):
    client, db = app_and_db
    now = datetime.now(timezone.utc)
    # Node A 100 % uptime, node B 50 % uptime.
    for i in range(4):
        _insert(db, now - timedelta(minutes=i), NODE_A, ok=True)
    for i in range(4):
        _insert(db, now - timedelta(minutes=i), NODE_B, ok=(i % 2 == 0))
    r = client.get("/api/v1/stats/top?metric=uptime&range=24h&limit=2")
    assert r.status_code == 200
    ranked = r.json()["ranked"]
    assert ranked[0]["node_url"] == NODE_A
    assert ranked[0]["uptime_pct"] >= ranked[1]["uptime_pct"]


def test_stats_top_errors_sorts_descending(app_and_db):
    client, db = app_and_db
    now = datetime.now(timezone.utc)
    # Node A clean, node B three errors.
    for i in range(5):
        _insert(db, now - timedelta(minutes=i), NODE_A, ok=True)
    for i in range(5):
        _insert(db, now - timedelta(minutes=i), NODE_B, ok=(i >= 3))
    r = client.get("/api/v1/stats/top?metric=errors&range=24h")
    assert r.status_code == 200
    ranked = r.json()["ranked"]
    assert ranked[0]["node_url"] == NODE_B
    assert ranked[0]["errors"] == 3
    assert ranked[1]["errors"] == 0


def test_stats_top_rejects_unknown_metric(app_and_db):
    client, _ = app_and_db
    r = client.get("/api/v1/stats/top?metric=bogus&range=24h")
    assert r.status_code == 422


# =============================================================================
#  /nodes/{url}/uptime-daily
# =============================================================================

def test_uptime_daily_fills_missing_days(app_and_db):
    client, db = app_and_db
    today = datetime.now(timezone.utc).date()
    # Only two days have data; the rest must come back as null-uptime entries.
    _insert(db, datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc), NODE_A, ok=True)
    _insert(db, datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=2), NODE_A, ok=True)
    r = client.get(f"/api/v1/nodes/{NODE_A}/uptime-daily?days=5")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 5
    uptime = body["uptime"]
    assert len(uptime) == 5  # contiguous
    # Endpoint is the most recent day.
    assert uptime[-1]["date"] == today.isoformat()
    # Today and day-2 have data; day-1, day-3, day-4 don't.
    with_data = [u for u in uptime if u["uptime_pct"] is not None]
    assert len(with_data) == 2
    for u in with_data:
        assert u["uptime_pct"] == 100.0


def test_uptime_daily_validates_days(app_and_db):
    client, _ = app_and_db
    r = client.get(f"/api/v1/nodes/{NODE_A}/uptime-daily?days=0")
    assert r.status_code == 422
    r = client.get(f"/api/v1/nodes/{NODE_A}/uptime-daily?days=91")
    assert r.status_code == 422


# =============================================================================
#  /stats/top — reverse metrics (latency_worst / uptime_worst)
# =============================================================================

def test_stats_top_latency_worst_sorts_descending(app_and_db):
    client, db = app_and_db
    now = datetime.now(timezone.utc)
    for i in range(3):
        _insert(db, now - timedelta(minutes=i), NODE_A, ok=True, latency=100)
        _insert(db, now - timedelta(minutes=i), NODE_B, ok=True, latency=500)
    r = client.get("/api/v1/stats/top?metric=latency_worst&range=24h&limit=2")
    assert r.status_code == 200
    ranked = r.json()["ranked"]
    # The slow node must be first when we ask for the worst.
    assert ranked[0]["node_url"] == NODE_B
    assert ranked[0]["avg_latency_ms"] > ranked[1]["avg_latency_ms"]


def test_stats_top_uptime_worst_sorts_ascending(app_and_db):
    client, db = app_and_db
    now = datetime.now(timezone.utc)
    for i in range(4):
        _insert(db, now - timedelta(minutes=i), NODE_A, ok=True)
    for i in range(4):
        _insert(db, now - timedelta(minutes=i), NODE_B, ok=(i % 2 == 0))
    r = client.get("/api/v1/stats/top?metric=uptime_worst&range=24h&limit=2")
    assert r.status_code == 200
    ranked = r.json()["ranked"]
    assert ranked[0]["node_url"] == NODE_B
    assert ranked[0]["uptime_pct"] <= ranked[1]["uptime_pct"]


# =============================================================================
#  /stats/chain-availability
# =============================================================================

def test_chain_availability_buckets_up_and_down(app_and_db):
    client, db = app_and_db
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    # Two nodes over a 30-minute span within the same 10-min bucket, one
    # fails in the first bucket — so the first bucket sees 1 up + 1 down.
    for i in range(3):  # 3 ticks within the first 10-min bucket
        _insert(db, now - timedelta(minutes=60 - i), NODE_A, ok=(i > 0))  # first tick fails
        _insert(db, now - timedelta(minutes=60 - i), NODE_B, ok=True)
    r = client.get("/api/v1/stats/chain-availability?range=24h")
    assert r.status_code == 200
    body = r.json()
    assert body["bucket_seconds"] == 600
    # Every returned bucket must preserve up + down == total.
    for p in body["points"]:
        assert p["up"] + p["down"] == p["total"]
    # Overall counts match the 6 inserts (5 ok + 1 fail).
    assert sum(p["up"] for p in body["points"]) == 5
    assert sum(p["down"] for p in body["points"]) == 1


def test_chain_availability_rejects_30d(app_and_db):
    client, _ = app_and_db
    r = client.get("/api/v1/stats/chain-availability?range=30d")
    assert r.status_code == 422


# =============================================================================
#  /stats/daily-comparison
# =============================================================================

def test_outages_filter_by_min_duration(app_and_db):
    client, db = app_and_db
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    # Node A: one short outage (60 s), one real outage (300 s).
    _insert(db, base + timedelta(seconds=0), NODE_A, ok=True)
    _insert(db, base + timedelta(seconds=60), NODE_A, ok=False)
    _insert(db, base + timedelta(seconds=120), NODE_A, ok=True)
    for i in range(5):
        _insert(db, base + timedelta(seconds=180 + i * 60), NODE_A, ok=False)
    _insert(db, base + timedelta(seconds=480), NODE_A, ok=True)

    r = client.get("/api/v1/outages?range=24h&min_duration_s=120")
    assert r.status_code == 200
    body = r.json()
    # Only the 300-s outage passes a 120-s threshold.
    assert body["min_duration_s"] == 120
    assert body["total"] == 1
    assert body["outages"][0]["severity"] == "real"
    assert body["outages"][0]["duration_s"] == 300


def test_outages_min_duration_validation(app_and_db):
    client, _ = app_and_db
    r = client.get("/api/v1/outages?min_duration_s=-1")
    assert r.status_code == 422
    r = client.get("/api/v1/outages?min_duration_s=86401")
    assert r.status_code == 422


def test_export_outages_csv_sets_attachment_and_escapes(app_and_db):
    client, db = app_and_db
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    _insert(db, base + timedelta(seconds=0), NODE_A, ok=True)
    for i in range(3):
        _insert(db, base + timedelta(seconds=60 + i * 60), NODE_A, ok=False)
    _insert(db, base + timedelta(seconds=240), NODE_A, ok=True)

    r = client.get("/api/v1/export/outages.csv?range=24h")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="outages-24h.csv"' in r.headers["content-disposition"]
    body = r.text.splitlines()
    assert body[0] == "node_url,start,end,duration_s,severity,error_sample,ongoing"
    assert len(body) == 2  # header + 1 outage
    # 3 × 60 s = 180 s ⇒ severity real.
    assert ",real," in body[1]
    assert body[1].startswith(f"{NODE_A},")


def test_export_outages_json_sets_attachment_and_filters(app_and_db):
    client, db = app_and_db
    base = datetime.now(timezone.utc) - timedelta(hours=1)
    # One real outage, one short.
    _insert(db, base + timedelta(seconds=0), NODE_A, ok=True)
    _insert(db, base + timedelta(seconds=60), NODE_A, ok=False)
    _insert(db, base + timedelta(seconds=120), NODE_A, ok=True)
    for i in range(4):
        _insert(db, base + timedelta(seconds=180 + i * 60), NODE_A, ok=False)
    _insert(db, base + timedelta(seconds=420), NODE_A, ok=True)

    r = client.get("/api/v1/export/outages.json?range=24h&severity=real")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert 'attachment; filename="outages-24h-real.json"' in r.headers["content-disposition"]
    import json as _json
    body = _json.loads(r.text)
    assert body["severity_filter"] == "real"
    assert body["total"] == 1
    assert body["outages"][0]["severity"] == "real"


def test_regions_aggregates_by_region(app_and_db):
    client, db = app_and_db
    now = datetime.now(timezone.utc)
    # Node A in eu-central, Node B in us-east. Different latencies, both
    # fully up — regional aggregates should average independently.
    for i in range(5):
        _insert(db, now - timedelta(minutes=i), NODE_A, ok=True, latency=100)
        _insert(db, now - timedelta(minutes=i), NODE_B, ok=True, latency=500)

    # The test fixture pins NODE_A region='eu-central' and NODE_B='us-west'
    # by default. Override so we can verify both anchored and un-anchored
    # regions make it through.
    import json, config, pathlib
    (pathlib.Path(db).parent / "nodes.json").write_text(json.dumps([
        {"url": NODE_A, "region": "eu-central"},
        {"url": NODE_B, "region": "us-east"},
    ]))

    r = client.get("/api/v1/regions")
    assert r.status_code == 200
    body = r.json()
    regions = {r["region"]: r for r in body["regions"]}
    assert "eu-central" in regions and "us-east" in regions

    eu = regions["eu-central"]
    assert eu["node_count"] == 1
    assert eu["lat"] is not None and eu["lng"] is not None
    assert eu["avg_latency_ms"] == 100.0
    assert eu["avg_uptime_pct_24h"] == 100.0
    assert eu["status"] == "ok"
    assert eu["nodes"][0]["url"] == NODE_A

    us = regions["us-east"]
    assert us["node_count"] == 1
    assert us["avg_latency_ms"] == 500.0


def test_regions_handles_anchorless_region(app_and_db, monkeypatch):
    client, db = app_and_db
    now = datetime.now(timezone.utc)
    import json, pathlib
    (pathlib.Path(db).parent / "nodes.json").write_text(json.dumps([
        {"url": NODE_A, "region": "global"},
        {"url": NODE_B, "region": "eu-central"},
    ]))
    _insert(db, now, NODE_A, ok=True)
    _insert(db, now, NODE_B, ok=True)

    r = client.get("/api/v1/regions")
    assert r.status_code == 200
    by = {r["region"]: r for r in r.json()["regions"]}
    # "global" exists in the response, its lat/lng are None (no anchor),
    # and it sorts after anchored regions because of the "lat is None"
    # tie-breaker in the response.
    assert by["global"]["lat"] is None
    assert by["global"]["lng"] is None
    # Anchored region precedes anchorless in the returned list.
    regions_order = [r["region"] for r in r.json()["regions"]]
    assert regions_order.index("eu-central") < regions_order.index("global")


def test_daily_comparison_partitions_three_windows(app_and_db):
    client, db = app_and_db
    now = datetime.now(timezone.utc)
    # Today window — drop a fast tick.
    _insert(db, now - timedelta(hours=1), NODE_A, ok=True, latency=100)
    # Yesterday window (24 h–48 h ago) — slow tick.
    _insert(db, now - timedelta(hours=36), NODE_A, ok=True, latency=400)
    # Last-week window (168 h–192 h ago) — medium tick.
    _insert(db, now - timedelta(hours=180), NODE_A, ok=True, latency=250)

    r = client.get("/api/v1/stats/daily-comparison")
    assert r.status_code == 200
    body = r.json()
    row = next(n for n in body["nodes"] if n["node_url"] == NODE_A)
    # Each window must pick up exactly its tick, no cross-window leakage.
    assert row["today"]["avg_latency_ms"] == 100
    assert row["yesterday"]["avg_latency_ms"] == 400
    assert row["lastweek"]["avg_latency_ms"] == 250
