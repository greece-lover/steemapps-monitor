"""GET /api/v1/sources/locations — geo-decorated source list.

Exercises the regions-map data path: primary monitor first, only active
participants from the participants table, lat/lng pulled from
config.REGION_COORDINATES, anchorless regions return null coords.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import database
import participants as participants_mod
from api import build_app


NODE_A = "https://a.example"


@pytest.fixture
def app_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "loc.sqlite"
    database.initialise(db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(config, "NODES_FILE", tmp_path / "nodes.json")
    (tmp_path / "nodes.json").write_text(json.dumps([
        {"url": NODE_A, "region": "eu-central"},
    ]))
    monkeypatch.setattr(config, "PRIMARY_SOURCE", {
        "label": "contabo-de-1",
        "steem_account": "greece-lover",
        "display_label": "Welako VM (DE)",
        "region": "eu-central",
        "primary": True,
    })
    app = build_app()
    return TestClient(app), db_path


def test_locations_includes_primary_first_with_eu_central_coords(app_db):
    client, _ = app_db
    r = client.get("/api/v1/sources/locations")
    assert r.status_code == 200
    body = r.json()
    assert body["sources"][0]["primary"] is True
    assert body["sources"][0]["steem_account"] == "greece-lover"
    # eu-central anchor in REGION_COORDINATES is (50.11, 8.68).
    assert body["sources"][0]["lat"] == pytest.approx(50.11)
    assert body["sources"][0]["lng"] == pytest.approx(8.68)
    assert body["sources"][0]["region_label"] == "Europe Central"


def test_locations_includes_active_participants_with_their_region(app_db):
    client, db = app_db
    p, _ = participants_mod.create_participant(
        steem_account="bob", display_label="Bob (US)", region="us-east", db_path=db,
    )
    r = client.get("/api/v1/sources/locations")
    sources = r.json()["sources"]
    bob = next(s for s in sources if s["steem_account"] == "bob")
    # us-east anchor: (40.71, -74.01)
    assert bob["lat"] == pytest.approx(40.71)
    assert bob["lng"] == pytest.approx(-74.01)
    assert bob["region"] == "us-east"
    assert bob["region_label"] == "US East"
    assert bob["primary"] is False


def test_locations_excludes_inactive_participants(app_db):
    client, db = app_db
    p, _ = participants_mod.create_participant(
        steem_account="eve", display_label="Eve", region="us-east", db_path=db,
    )
    participants_mod.set_active(p.id, False, db_path=db)
    r = client.get("/api/v1/sources/locations")
    accounts = {s["steem_account"] for s in r.json()["sources"]}
    assert "eve" not in accounts


def test_locations_returns_null_coords_for_anchorless_region(app_db):
    """Sources in `global` or `unknown` regions still appear in the
    response, but with lat=lng=None — the map skips them, the
    accompanying tooling can still list them."""
    client, db = app_db
    participants_mod.create_participant(
        steem_account="cdn", display_label="CDN edge", region="global", db_path=db,
    )
    r = client.get("/api/v1/sources/locations")
    cdn = next(s for s in r.json()["sources"] if s["steem_account"] == "cdn")
    assert cdn["region"] == "global"
    assert cdn["lat"] is None
    assert cdn["lng"] is None


def test_locations_carries_24h_count_and_last_seen(app_db):
    client, db = app_db
    p, _ = participants_mod.create_participant(
        steem_account="bob", display_label="Bob (US)", region="us-east", db_path=db,
    )
    # Insert a measurement attributed to Bob.
    from datetime import datetime, timezone
    iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    database.insert_measurement(
        database.Measurement(
            timestamp=iso, node_url=NODE_A, success=True, latency_ms=200,
            block_height=1000, error_message=None, source_location="Bob (US)",
        ),
        db,
    )
    r = client.get("/api/v1/sources/locations")
    bob = next(s for s in r.json()["sources"] if s["steem_account"] == "bob")
    assert bob["measurements_24h"] == 1
    assert bob["last_seen"] == iso


def test_locations_unknown_region_string_falls_back_to_label_equal_to_id(app_db):
    """A region value not present in REGION_COORDINATES (e.g. someone
    registered through admin route with a custom string) still renders —
    region_label falls back to the raw region id, lat/lng come back null."""
    client, db = app_db
    # Insert directly via participants_mod with an off-list region.
    participants_mod.create_participant(
        steem_account="alice", display_label="Alice (Mars)", region="mars-base", db_path=db,
    )
    r = client.get("/api/v1/sources/locations")
    alice = next(s for s in r.json()["sources"] if s["steem_account"] == "alice")
    assert alice["region_label"] == "mars-base"
    assert alice["lat"] is None
    assert alice["lng"] is None
