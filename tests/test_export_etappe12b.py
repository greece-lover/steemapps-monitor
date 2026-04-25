"""GET /api/v1/export/* — bulk export endpoints (Etappe 12b).

Three endpoints under test:
  - /api/v1/export/measurements?range&node&source&format
  - /api/v1/export/aggregates?range&granularity&node&source&format
  - /api/v1/export/sources

Streaming: we don't measure memory here, but we do verify that the
output shape matches the format selector and that filters compose
correctly. The DB layer's `stream_*` helpers carry the real heavy-
lifting test in a separate database-level test if needed.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import database
from api import build_app


NODE_A = "https://a.example"
NODE_B = "https://b.example"


@pytest.fixture
def app_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "export.sqlite"
    database.initialise(db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(config, "NODES_FILE", tmp_path / "nodes.json")
    (tmp_path / "nodes.json").write_text(json.dumps([
        {"url": NODE_A, "region": "eu-central"},
        {"url": NODE_B, "region": "us-east"},
    ]))
    app = build_app()
    return TestClient(app), db_path


def _seed(db_path: Path, *, count_a: int = 60, count_b: int = 60,
          src_a: str = "Welako VM (DE)", src_b: str = "Bob (US)") -> None:
    """Insert `count_a` ticks for NODE_A and `count_b` for NODE_B in the
    last hour, every minute. NODE_A is healthy, NODE_B fails on every
    tenth row so the export has both successes and failures to render."""
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    rows = []
    for i in range(count_a):
        ts = (now - timedelta(minutes=count_a - i)).isoformat().replace("+00:00", "Z")
        rows.append((ts, NODE_A, 1, 100 + (i % 5) * 10, 1000, None, src_a))
    for i in range(count_b):
        ok = (i % 10) != 0
        ts = (now - timedelta(minutes=count_b - i)).isoformat().replace("+00:00", "Z")
        rows.append((
            ts, NODE_B, 1 if ok else 0,
            (250 + (i % 7) * 5) if ok else None,
            1000 if ok else None,
            None if ok else "timeout",
            src_b,
        ))
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executemany(
            "INSERT INTO measurements "
            "(timestamp, node_url, success, latency_ms, block_height, error_message, source_location) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


# =============================================================================
#  /api/v1/export/measurements
# =============================================================================

def test_measurements_csv_default_format_returns_streaming_csv(app_db):
    client, db = app_db
    _seed(db, count_a=10, count_b=10)
    r = client.get("/api/v1/export/measurements?range=24h")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    text = r.text
    lines = text.strip().split("\n")
    # Header + 20 rows.
    assert lines[0] == "timestamp,node_url,success,latency_ms,block_height,error_message,source_location"
    assert len(lines) == 21


def test_measurements_csv_node_filter_narrows_to_one_node(app_db):
    client, db = app_db
    _seed(db, count_a=10, count_b=10)
    r = client.get(f"/api/v1/export/measurements?range=24h&node={NODE_A}")
    assert r.status_code == 200
    text = r.text
    # Only NODE_A rows — no `b.example` anywhere except the header.
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 10
    assert all(row["node_url"] == NODE_A for row in rows)


def test_measurements_csv_source_filter_works(app_db):
    client, db = app_db
    _seed(db, count_a=5, count_b=5, src_a="Welako VM (DE)", src_b="Bob (US)")
    r = client.get("/api/v1/export/measurements?range=24h&source=Bob+%28US%29")
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 5
    assert all(row["source_location"] == "Bob (US)" for row in rows)


def test_measurements_csv_unknown_node_404(app_db):
    client, _ = app_db
    r = client.get("/api/v1/export/measurements?range=24h&node=https://ghost.example")
    assert r.status_code == 404


def test_measurements_csv_invalid_range_422(app_db):
    client, _ = app_db
    r = client.get("/api/v1/export/measurements?range=99d")
    assert r.status_code == 422


def test_measurements_jsonl_one_object_per_line(app_db):
    client, db = app_db
    _seed(db, count_a=3, count_b=3)
    r = client.get("/api/v1/export/measurements?range=24h&format=jsonl")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [ln for ln in r.text.strip().split("\n") if ln]
    assert len(lines) == 6
    for ln in lines:
        obj = json.loads(ln)
        assert {"timestamp", "node_url", "success", "latency_ms"} <= set(obj.keys())
        assert isinstance(obj["success"], bool)


def test_measurements_json_envelope_has_metadata(app_db):
    client, db = app_db
    _seed(db, count_a=2, count_b=2)
    r = client.get("/api/v1/export/measurements?range=24h&format=json")
    assert r.status_code == 200
    body = json.loads(r.text)
    assert body["range"] == "24h"
    assert "window" in body and "start" in body["window"]
    assert "measurements" in body
    assert len(body["measurements"]) == 4


def test_measurements_csv_filename_carries_filters(app_db):
    client, db = app_db
    _seed(db, count_a=1, count_b=1)
    r = client.get(f"/api/v1/export/measurements?range=7d&node={NODE_A}")
    cd = r.headers.get("content-disposition", "")
    assert "measurements-7d" in cd
    assert "a.example" in cd


def test_measurements_csv_empty_window_returns_only_header(app_db):
    client, _ = app_db
    # No data inserted.
    r = client.get("/api/v1/export/measurements?range=24h")
    assert r.status_code == 200
    assert r.text.strip() == "timestamp,node_url,success,latency_ms,block_height,error_message,source_location"


# =============================================================================
#  /api/v1/export/aggregates
# =============================================================================

def test_aggregates_hourly_default_csv(app_db):
    client, db = app_db
    _seed(db, count_a=10, count_b=10)
    r = client.get("/api/v1/export/aggregates?range=24h&granularity=hourly")
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    # Two nodes × however many populated hours.
    assert len(rows) > 0
    for row in rows:
        # Hourly bucket shape.
        assert row["bucket"].endswith(":00:00Z")
        assert row["node_url"] in (NODE_A, NODE_B)
        assert int(row["total"]) > 0


def test_aggregates_daily_bucket_shape(app_db):
    client, db = app_db
    _seed(db, count_a=5, count_b=5)
    r = client.get("/api/v1/export/aggregates?range=24h&granularity=daily")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    for row in rows:
        # Daily bucket: YYYY-MM-DD only.
        assert len(row["bucket"]) == 10
        assert row["bucket"][4] == "-" and row["bucket"][7] == "-"


def test_aggregates_node_b_has_errors_in_uptime_pct(app_db):
    """NODE_B fails on every 10th row → uptime_pct < 100 in its bucket."""
    client, db = app_db
    _seed(db, count_a=20, count_b=20)
    r = client.get(f"/api/v1/export/aggregates?range=24h&granularity=hourly&node={NODE_B}")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows
    # Total uptime across all rows should be < 100 since b fails periodically.
    total_ok = sum(int(r["ok"]) for r in rows)
    total_total = sum(int(r["total"]) for r in rows)
    assert total_ok < total_total


def test_aggregates_invalid_granularity_422(app_db):
    client, _ = app_db
    r = client.get("/api/v1/export/aggregates?range=24h&granularity=monthly")
    assert r.status_code == 422


def test_aggregates_jsonl_format(app_db):
    client, db = app_db
    _seed(db, count_a=5, count_b=5)
    r = client.get("/api/v1/export/aggregates?range=24h&granularity=hourly&format=jsonl")
    lines = [ln for ln in r.text.strip().split("\n") if ln]
    for ln in lines:
        obj = json.loads(ln)
        assert {"bucket", "node_url", "total", "ok", "uptime_pct"} <= set(obj.keys())


# =============================================================================
#  /api/v1/export/sources
# =============================================================================

def test_export_sources_lists_distinct_source_locations(app_db):
    client, db = app_db
    _seed(db, src_a="Welako VM (DE)", src_b="Bob (US)")
    r = client.get("/api/v1/export/sources")
    assert r.status_code == 200
    body = r.json()
    assert set(body["sources"]) == {"Welako VM (DE)", "Bob (US)"}


def test_export_sources_returns_empty_list_when_no_data(app_db):
    client, _ = app_db
    r = client.get("/api/v1/export/sources")
    assert r.status_code == 200
    assert r.json()["sources"] == []


# =============================================================================
#  Outage export — new source filter
# =============================================================================

def test_outages_csv_accepts_source_filter_param(app_db):
    """The new `source` query param is accepted on outages.csv. Filtering
    correctness is covered by the underlying outage detector tests; here
    we just pin that the param is wired through and an unknown source
    returns an empty result set instead of a 422."""
    client, _ = app_db
    r = client.get("/api/v1/export/outages.csv?source=does-not-exist")
    assert r.status_code == 200
    # Header only, no data rows.
    assert r.text.strip() == "node_url,start,end,duration_s,severity,error_sample,ongoing"


def test_outages_json_includes_source_filter_in_envelope(app_db):
    client, _ = app_db
    r = client.get("/api/v1/export/outages.json?source=Welako+VM+%28DE%29")
    assert r.status_code == 200
    body = json.loads(r.text)
    assert body["source_filter"] == "Welako VM (DE)"


# =============================================================================
#  Streaming behaviour — confirm the DB layer is generator-based (O(1)
#  memory). The TestClient buffers chunks before iter_text() so we can't
#  prove streaming through HTTP — but we can prove it at the source.
# =============================================================================

def test_stream_measurements_returns_a_generator_not_a_list(app_db):
    """The DB-layer streaming helper must return a generator so the
    FastAPI StreamingResponse never materialises the full result set
    in memory. A regression to fetchall() would silently turn a 90-day
    export into a multi-gigabyte allocation."""
    import types
    _, db = app_db
    _seed(db, count_a=1, count_b=1)
    from datetime import datetime, timezone
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gen = database.stream_measurements(
        start_iso="2000-01-01T00:00:00Z", end_iso=iso, db_path=db,
    )
    assert isinstance(gen, types.GeneratorType)
    # Consume one item, confirm the generator is alive (not pre-materialised).
    first = next(gen)
    assert "node_url" in first
    # Exhaust to release the connection.
    list(gen)


def test_stream_aggregates_returns_a_generator_not_a_list(app_db):
    import types
    _, db = app_db
    _seed(db, count_a=5, count_b=5)
    from datetime import datetime, timezone
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gen = database.stream_aggregates(
        start_iso="2000-01-01T00:00:00Z", end_iso=iso,
        granularity="hourly", db_path=db,
    )
    assert isinstance(gen, types.GeneratorType)
    list(gen)


def test_measurements_endpoint_returns_full_dataset_for_1100_rows(app_db):
    """End-to-end smoke at a row count that crosses the fetchmany(1000)
    boundary — proves the second chunk is read and emitted, even if the
    TestClient buffers the chunks before handing them back."""
    client, db = app_db
    _seed(db, count_a=1100, count_b=0)
    r = client.get("/api/v1/export/measurements?range=24h")
    assert r.status_code == 200
    lines = [ln for ln in r.text.strip().split("\n") if ln]
    assert len(lines) == 1101                 # header + 1100 data rows
