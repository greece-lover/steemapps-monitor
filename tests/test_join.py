"""Self-service onboarding — /api/v1/join/register + /api/v1/join/regions.

Single-step flow: form → chain existence check → API key. No memo
verification, no pending state, no listener. Every test starts with a
fresh DB and a stubbed account validator so nothing reaches the live
chain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import database
import join as join_mod
import participants as participants_mod
from api import build_app


NODE_A = "https://a.example"


@pytest.fixture
def app_db(tmp_path: Path, monkeypatch):
    """Fresh DB + isolated nodes.json; stub the chain validator so the
    register route never reaches out over the network."""
    db_path = tmp_path / "join.sqlite"
    database.initialise(db_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(config, "NODES_FILE", tmp_path / "nodes.json")
    (tmp_path / "nodes.json").write_text(json.dumps([
        {"url": NODE_A, "region": "eu-central"},
    ]))

    # Stub default_account_validator — every account "exists" by default.
    # Individual tests override this when they need a 404 path.
    monkeypatch.setattr(join_mod, "default_account_validator", lambda acc: True)

    app = build_app()
    return TestClient(app), db_path


# =============================================================================
#  /api/v1/join/regions
# =============================================================================

def test_regions_returns_known_set(app_db):
    client, _ = app_db
    r = client.get("/api/v1/join/regions")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()["regions"]}
    assert "eu-central" in ids
    assert "us-east" in ids


# =============================================================================
#  /api/v1/join/register — happy path
# =============================================================================

def test_register_happy_path_returns_api_key_and_creates_participant(app_db):
    client, db = app_db
    r = client.post(
        "/api/v1/join/register",
        json={"steem_account": "alice", "display_label": "Alice (US)", "region": "us-east"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["api_key"].startswith(participants_mod.KEY_PREFIX)
    assert body["steem_account"] == "alice"
    assert body["display_label"] == "Alice (US)"
    assert body["region"] == "us-east"

    # The freshly-issued key must work for ingest immediately.
    p = participants_mod.verify_api_key(body["api_key"], db_path=db)
    assert p is not None
    assert p.steem_account == "alice"
    assert p.display_label == "Alice (US)"
    assert p.region == "us-east"
    assert p.active is True


def test_register_persisted_note_marks_self_service(app_db):
    client, db = app_db
    client.post(
        "/api/v1/join/register",
        json={"steem_account": "alice", "display_label": "Alice", "region": "us-east"},
    )
    rows = participants_mod.list_participants(db_path=db)
    assert rows[0].note == "self-service join"


# =============================================================================
#  Validation failures — pydantic + join.JoinError
# =============================================================================

def test_register_rejects_invalid_account_name(app_db):
    """Bad chars / wrong length: pydantic catches some shapes (422),
    join.register catches the rest (400). Both are valid 'no' answers."""
    client, _ = app_db
    r = client.post(
        "/api/v1/join/register",
        json={"steem_account": "Bad-Name!", "display_label": "x", "region": "us-east"},
    )
    assert r.status_code in (400, 422)


def test_register_rejects_unknown_steem_account(app_db, monkeypatch):
    client, _ = app_db
    monkeypatch.setattr(join_mod, "default_account_validator", lambda acc: False)
    r = client.post(
        "/api/v1/join/register",
        json={"steem_account": "ghost", "display_label": "Ghost", "region": "us-east"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "account_not_found"


def test_register_rejects_already_registered_account(app_db):
    client, db = app_db
    participants_mod.create_participant(
        steem_account="alice", display_label="Alice", region="us-east", db_path=db,
    )
    r = client.post(
        "/api/v1/join/register",
        json={"steem_account": "alice", "display_label": "Alice 2", "region": "us-east"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "already_registered"


def test_register_rejects_invalid_region(app_db):
    client, _ = app_db
    r = client.post(
        "/api/v1/join/register",
        json={"steem_account": "alice", "display_label": "Alice", "region": "antarctica"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_region"


def test_register_rejects_empty_label(app_db):
    """Pydantic enforces min_length=1; the field-level check in join.py
    is the second line of defence for whitespace-only input."""
    client, _ = app_db
    r = client.post(
        "/api/v1/join/register",
        json={"steem_account": "alice", "display_label": "   ", "region": "us-east"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_label"


def test_register_503_when_chain_unreachable(app_db, monkeypatch):
    client, _ = app_db
    def _raise(_):
        raise join_mod.JoinError(503, "chain_unreachable", "no node answered")
    monkeypatch.setattr(join_mod, "default_account_validator", _raise)
    r = client.post(
        "/api/v1/join/register",
        json={"steem_account": "alice", "display_label": "Alice", "region": "us-east"},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "chain_unreachable"


# =============================================================================
#  Sanity checks on the register helper itself
# =============================================================================

def test_register_helper_lowercases_account(tmp_path):
    """Mixed-case input must normalise to the canonical lowercase form
    before insert — otherwise the later UNIQUE-on-account check would
    let `Alice` and `alice` co-exist."""
    db_path = tmp_path / "join.sqlite"
    database.initialise(db_path)
    reg = join_mod.register_participant(
        steem_account="Alice",
        display_label="Alice",
        region="us-east",
        db_path=db_path,
        account_validator=lambda acc: True,
    )
    assert reg.participant.steem_account == "alice"


def test_register_helper_409_on_race(tmp_path):
    """Two near-simultaneous registers for the same account: the second
    must surface 409, not crash on the UNIQUE constraint."""
    db_path = tmp_path / "join.sqlite"
    database.initialise(db_path)
    join_mod.register_participant(
        steem_account="alice", display_label="A", region="us-east",
        db_path=db_path, account_validator=lambda acc: True,
    )
    with pytest.raises(join_mod.JoinError) as excinfo:
        join_mod.register_participant(
            steem_account="alice", display_label="A2", region="us-east",
            db_path=db_path, account_validator=lambda acc: True,
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "already_registered"
