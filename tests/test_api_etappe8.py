"""Phase 6 Etappe 8 — community ingest, admin, sources.

Mirrors the test_api_phase6 layout: a fresh app+DB per test, the dev API
key is registered in-test by calling the admin route or the helper module
directly. None of these tests make outbound network calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import database
import ingest as ingest_mod
import participants as participants_mod
from api import build_app

NODE_A = "https://a.example"
NODE_B = "https://b.example"
ADMIN_TOKEN = "test-admin-token-not-for-prod"


@pytest.fixture
def app_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "etappe8.sqlite"
    database.initialise(db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(config, "NODES_FILE", tmp_path / "nodes.json")
    (tmp_path / "nodes.json").write_text(json.dumps([
        {"url": NODE_A, "region": "eu-central"},
        {"url": NODE_B, "region": "us-west"},
    ]))
    monkeypatch.setattr(config, "ADMIN_TOKEN", ADMIN_TOKEN)
    app = build_app()
    return TestClient(app), db_path


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _create_participant(db_path: Path, label: str = "Tester (XX)", account: str = "tester") -> tuple[participants_mod.Participant, str]:
    return participants_mod.create_participant(
        steem_account=account, display_label=label, region="us-west", db_path=db_path
    )


def _measurement(ts: datetime, url: str = NODE_A, ok: bool = True, latency: int | None = 200) -> dict:
    return {
        "timestamp": _iso(ts),
        "node_url": url,
        "success": ok,
        "latency_ms": latency if ok else None,
        "block_height": 1000 if ok else None,
        "error_category": None if ok else "timeout",
    }


# =============================================================================
#  /api/v1/ingest — happy path and persistence
# =============================================================================

def test_ingest_persists_measurement_with_source_location(app_db):
    client, db = app_db
    _, key = _create_participant(db, label="Tester (US)")
    now = datetime.now(timezone.utc)
    body = {"measurements": [_measurement(now)]}
    r = client.post("/api/v1/ingest", json=body, headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["accepted"] == 1
    assert out["rejected"] == []
    rows = database.get_recent_measurements(NODE_A, db_path=db)
    assert rows[0]["source_location"] == "Tester (US)"
    assert rows[0]["latency_ms"] == 200


def test_ingest_returns_remaining_tokens(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    now = datetime.now(timezone.utc)
    r = client.post(
        "/api/v1/ingest",
        json={"measurements": [_measurement(now), _measurement(now)]},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    # Burst capacity 100, batch of 2 → 98 remaining. Allow ±1 for the
    # tiny refill that happens during the call itself.
    assert 96 <= r.json()["rate_limit_remaining"] <= 100


# =============================================================================
#  Authentication
# =============================================================================

def test_ingest_rejects_missing_api_key(app_db):
    client, db = app_db
    _create_participant(db)
    now = datetime.now(timezone.utc)
    r = client.post("/api/v1/ingest", json={"measurements": [_measurement(now)]})
    assert r.status_code == 401
    assert "X-API-Key" in r.json()["detail"]


def test_ingest_rejects_unknown_api_key(app_db):
    client, _ = app_db
    now = datetime.now(timezone.utc)
    r = client.post(
        "/api/v1/ingest",
        json={"measurements": [_measurement(now)]},
        headers={"X-API-Key": "sapk_definitely-not-a-real-key"},
    )
    assert r.status_code == 401


def test_ingest_rejects_deactivated_participant(app_db):
    client, db = app_db
    p, key = _create_participant(db)
    participants_mod.set_active(p.id, False, db_path=db)
    now = datetime.now(timezone.utc)
    r = client.post(
        "/api/v1/ingest",
        json={"measurements": [_measurement(now)]},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 401
    # Same wording as wrong-key — must not let a probe distinguish
    # "deactivated" from "never existed".
    assert r.json()["detail"] == "invalid or inactive api key"


def test_ingest_rejects_malformed_api_key(app_db):
    client, _ = app_db
    now = datetime.now(timezone.utc)
    r = client.post(
        "/api/v1/ingest",
        json={"measurements": [_measurement(now)]},
        headers={"X-API-Key": "no-prefix-here"},
    )
    assert r.status_code == 401


# =============================================================================
#  Validation — timestamp window, node membership, latency bounds
# =============================================================================

def test_ingest_rejects_timestamp_too_old(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    too_old = datetime.now(timezone.utc) - timedelta(minutes=16)
    r = client.post(
        "/api/v1/ingest",
        json={"measurements": [_measurement(too_old)]},
        headers={"X-API-Key": key},
    )
    body = r.json()
    assert r.status_code == 200
    assert body["accepted"] == 0
    assert body["rejected"][0]["reason"] == "timestamp_too_old"


def test_ingest_rejects_timestamp_in_future(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    future = datetime.now(timezone.utc) + timedelta(minutes=2)
    r = client.post(
        "/api/v1/ingest",
        json={"measurements": [_measurement(future)]},
        headers={"X-API-Key": key},
    )
    assert r.json()["rejected"][0]["reason"] == "timestamp_future"


def test_ingest_rejects_unknown_node(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    now = datetime.now(timezone.utc)
    m = _measurement(now, url="https://ghost.example")
    r = client.post(
        "/api/v1/ingest", json={"measurements": [m]}, headers={"X-API-Key": key}
    )
    assert r.json()["rejected"][0]["reason"] == "unknown_node"


def test_ingest_rejects_latency_out_of_range(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    now = datetime.now(timezone.utc)
    m = _measurement(now, latency=99_999)
    r = client.post(
        "/api/v1/ingest", json={"measurements": [m]}, headers={"X-API-Key": key}
    )
    assert r.json()["rejected"][0]["reason"] == "latency_out_of_range"


def test_ingest_rejects_success_without_latency(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    now = datetime.now(timezone.utc)
    m = _measurement(now)
    m["latency_ms"] = None
    r = client.post(
        "/api/v1/ingest", json={"measurements": [m]}, headers={"X-API-Key": key}
    )
    assert r.json()["rejected"][0]["reason"] == "latency_inconsistent"


def test_ingest_mixed_batch_partial_success(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    now = datetime.now(timezone.utc)
    body = {"measurements": [
        _measurement(now),                                       # OK
        _measurement(now, url="https://ghost.example"),          # unknown_node
        _measurement(now, ok=False, latency=None),               # OK (failed tick)
        _measurement(now - timedelta(minutes=20)),               # too_old
    ]}
    r = client.post("/api/v1/ingest", json=body, headers={"X-API-Key": key})
    out = r.json()
    assert out["accepted"] == 2
    rejected_idxs = sorted(rj["index"] for rj in out["rejected"])
    assert rejected_idxs == [1, 3]


def test_ingest_rejects_batch_over_max_size(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    now = datetime.now(timezone.utc)
    body = {"measurements": [_measurement(now) for _ in range(ingest_mod.MAX_BATCH_SIZE + 1)]}
    r = client.post("/api/v1/ingest", json=body, headers={"X-API-Key": key})
    assert r.status_code == 422  # pydantic validation


def test_ingest_rejects_empty_batch(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    r = client.post("/api/v1/ingest", json={"measurements": []}, headers={"X-API-Key": key})
    assert r.status_code == 422


# =============================================================================
#  Rate limit — 100 burst, then 429
# =============================================================================

def test_ingest_rate_limit_triggers_429(app_db):
    client, db = app_db
    _, key = _create_participant(db)
    now = datetime.now(timezone.utc)
    # Drain the burst with one full-burst-sized batch.
    full = {"measurements": [_measurement(now) for _ in range(ingest_mod.RATE_LIMIT_BURST)]}
    r = client.post("/api/v1/ingest", json=full, headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    # Now a single extra row must hit 429 — the per-second refill is too
    # slow (≈0.194 tok/s) to refill 1 token within the test's wall clock.
    r2 = client.post(
        "/api/v1/ingest",
        json={"measurements": [_measurement(now)]},
        headers={"X-API-Key": key},
    )
    assert r2.status_code == 429
    assert "rate limit" in r2.json()["detail"].lower()


# =============================================================================
#  Admin routes
# =============================================================================

def _admin(headers: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    if headers:
        h.update(headers)
    return h


def test_admin_create_participant_returns_plaintext_key_once(app_db):
    client, _ = app_db
    r = client.post(
        "/api/v1/admin/participants",
        json={"steem_account": "alice", "display_label": "Alice (US)", "region": "us-east"},
        headers=_admin(),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["api_key"].startswith("sapk_")
    assert body["steem_account"] == "alice"
    assert body["active"] is True
    # Listing again must NOT include the plain key.
    list_r = client.get("/api/v1/admin/participants", headers=_admin())
    assert list_r.status_code == 200
    rows = list_r.json()["participants"]
    assert len(rows) == 1
    assert "api_key" not in rows[0]


def test_admin_routes_reject_missing_token(app_db):
    client, _ = app_db
    r = client.post(
        "/api/v1/admin/participants",
        json={"steem_account": "alice", "display_label": "Alice"},
    )
    assert r.status_code == 401


def test_admin_routes_reject_wrong_token(app_db):
    client, _ = app_db
    r = client.get(
        "/api/v1/admin/participants",
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert r.status_code == 401


def test_admin_disabled_when_token_unset(app_db, monkeypatch):
    client, _ = app_db
    monkeypatch.setattr(config, "ADMIN_TOKEN", None)
    r = client.get(
        "/api/v1/admin/participants",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
    )
    assert r.status_code == 503
    assert "admin disabled" in r.json()["detail"]


def test_admin_create_duplicate_steem_account_409(app_db):
    client, _ = app_db
    payload = {"steem_account": "alice", "display_label": "Alice 1"}
    assert client.post("/api/v1/admin/participants", json=payload, headers=_admin()).status_code == 201
    payload2 = {"steem_account": "alice", "display_label": "Alice 2"}
    r = client.post("/api/v1/admin/participants", json=payload2, headers=_admin())
    assert r.status_code == 409
    assert "alice" in r.json()["detail"]


def test_admin_patch_deactivates_participant(app_db):
    client, db = app_db
    p, key = _create_participant(db, label="Tester", account="tester")
    r = client.patch(
        f"/api/v1/admin/participants/{p.id}",
        json={"active": False},
        headers=_admin(),
    )
    assert r.status_code == 200
    assert r.json()["active"] is False
    # And the key must now bounce on ingest.
    now = datetime.now(timezone.utc)
    ing = client.post(
        "/api/v1/ingest",
        json={"measurements": [_measurement(now)]},
        headers={"X-API-Key": key},
    )
    assert ing.status_code == 401


def test_admin_delete_removes_participant(app_db):
    client, db = app_db
    p, _ = _create_participant(db)
    r = client.delete(f"/api/v1/admin/participants/{p.id}", headers=_admin())
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    # 404 the second time round.
    r2 = client.delete(f"/api/v1/admin/participants/{p.id}", headers=_admin())
    assert r2.status_code == 404


def test_admin_patch_404_for_unknown_id(app_db):
    client, _ = app_db
    r = client.patch(
        "/api/v1/admin/participants/9999",
        json={"active": False},
        headers=_admin(),
    )
    assert r.status_code == 404


# =============================================================================
#  /api/v1/sources
# =============================================================================

def test_sources_includes_primary_monitor_first(app_db, monkeypatch):
    client, _ = app_db
    monkeypatch.setattr(config, "PRIMARY_SOURCE", {
        "label": "contabo-de-1",
        "steem_account": "greece-lover",
        "display_label": "Welako VM (DE)",
        "region": "eu-central",
        "primary": True,
    })
    r = client.get("/api/v1/sources")
    assert r.status_code == 200
    sources = r.json()["sources"]
    assert sources[0]["primary"] is True
    assert sources[0]["steem_account"] == "greece-lover"


def test_sources_lists_active_participants_with_counts(app_db):
    client, db = app_db
    p, _ = _create_participant(db, label="Bob (US)", account="bob")
    # Ingest a couple of rows attributed to Bob to populate the counts.
    now = datetime.now(timezone.utc)
    for _ in range(3):
        database.insert_measurement(
            database.Measurement(
                timestamp=_iso(now),
                node_url=NODE_A,
                success=True,
                latency_ms=200,
                block_height=1000,
                error_message=None,
                source_location="Bob (US)",
            ),
            db,
        )
    r = client.get("/api/v1/sources")
    sources = r.json()["sources"]
    bob = next(s for s in sources if s["steem_account"] == "bob")
    assert bob["measurements_24h"] == 3
    assert bob["measurements_7d"] == 3
    assert bob["region"] == "us-west"


def test_sources_excludes_deactivated_participants(app_db):
    client, db = app_db
    p, _ = _create_participant(db, label="Eve (Inactive)", account="eve")
    participants_mod.set_active(p.id, False, db_path=db)
    r = client.get("/api/v1/sources")
    sources = r.json()["sources"]
    assert all(s["steem_account"] != "eve" for s in sources)


# =============================================================================
#  /api/v1/nodes — bootstrap helper for the participant script
# =============================================================================

def test_nodes_endpoint_returns_url_and_region(app_db):
    client, _ = app_db
    r = client.get("/api/v1/nodes")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    assert {n["url"] for n in nodes} == {NODE_A, NODE_B}
    assert all("region" in n for n in nodes)


# =============================================================================
#  Pure-module unit tests — RateLimiter, validate_row, normalise_timestamp
# =============================================================================

def test_rate_limiter_grants_within_burst_then_denies(monkeypatch):
    rl = ingest_mod.RateLimiter(capacity=10, per_hour=3600)
    # Pin the clock so the tiny inter-call refill doesn't muddy the
    # exact-token assertions below.
    monkeypatch.setattr(rl, "_now", lambda: 1000.0)
    granted, remaining = rl.consume("k", 7)
    assert granted is True and remaining == 3
    granted2, remaining2 = rl.consume("k", 3)
    assert granted2 is True and remaining2 == 0
    granted3, _ = rl.consume("k", 1)
    assert granted3 is False


def test_rate_limiter_refills_with_time(monkeypatch):
    rl = ingest_mod.RateLimiter(capacity=10, per_hour=3600)  # 1 token per second
    fake_now = [1000.0]
    monkeypatch.setattr(rl, "_now", lambda: fake_now[0])
    rl.consume("k", 10)  # drain
    fake_now[0] += 3.5
    granted, remaining = rl.consume("k", 3)
    assert granted is True
    # After 3.5 s of refill we have 3.5 tokens; consuming 3 leaves 0.5.
    assert 0.4 <= remaining <= 0.6


def test_validate_row_each_failure_path():
    nodes = {NODE_A}
    now = datetime.now(timezone.utc)
    base = {"node_url": NODE_A, "timestamp": _iso(now), "success": True, "latency_ms": 200}

    assert ingest_mod.validate_row(base, known_nodes=nodes, now=now) is None

    bad_node = {**base, "node_url": "https://ghost.example"}
    assert ingest_mod.validate_row(bad_node, known_nodes=nodes, now=now) == "unknown_node"

    bad_ts = {**base, "timestamp": "not-an-iso"}
    assert ingest_mod.validate_row(bad_ts, known_nodes=nodes, now=now) == "timestamp_invalid"

    too_old = {**base, "timestamp": _iso(now - timedelta(minutes=20))}
    assert ingest_mod.validate_row(too_old, known_nodes=nodes, now=now) == "timestamp_too_old"

    future = {**base, "timestamp": _iso(now + timedelta(minutes=2))}
    assert ingest_mod.validate_row(future, known_nodes=nodes, now=now) == "timestamp_future"

    bad_lat = {**base, "latency_ms": 99_999}
    assert ingest_mod.validate_row(bad_lat, known_nodes=nodes, now=now) == "latency_out_of_range"

    inconsistent = {**base, "latency_ms": None}
    assert ingest_mod.validate_row(inconsistent, known_nodes=nodes, now=now) == "latency_inconsistent"


def test_normalise_timestamp_canonical_shape():
    out = ingest_mod.normalise_timestamp("2026-04-25T10:30:45.123456+00:00")
    assert out == "2026-04-25T10:30:45Z"
    out2 = ingest_mod.normalise_timestamp("2026-04-25T10:30:45Z")
    assert out2 == "2026-04-25T10:30:45Z"
