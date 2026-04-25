"""Participant management — registration, key hashing, lookup.

External contributors (witnesses, node operators) get an API key once via
the admin route and use it to POST measurements to /api/v1/ingest. This
module owns:

- Plaintext key generation (`sapk_` prefix, base64url-encoded random)
- bcrypt hashing + SHA-256 lookup index (see SCHEMA in database.py)
- CRUD over the `participants` table
- Verification of an inbound key against an active participant row

Lookup is O(1) on the SHA-256 column; bcrypt is only invoked once the
candidate row is in hand. Inactive participants are filtered out at the
verification layer so a deactivated key fails immediately, even if a
race left it cached on the participant side.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import bcrypt

from database import DB_PATH, connect


# Keys are prefixed so an operator who pastes one into a log immediately
# sees what kind of secret it is, and so we can revoke a leaked-format
# scan downstream. 32 bytes = 256 bits of entropy from secrets.token_urlsafe.
KEY_PREFIX = "sapk_"
KEY_RANDOM_BYTES = 32


@dataclass
class Participant:
    id: int
    steem_account: str
    display_label: str
    region: Optional[str]
    created_at: str
    active: bool
    note: Optional[str]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def generate_api_key() -> str:
    """Return a fresh plaintext API key. Caller is responsible for showing
    it to the operator exactly once — only the hashes are persisted."""
    return KEY_PREFIX + secrets.token_urlsafe(KEY_RANDOM_BYTES)


def lookup_hash(plain_key: str) -> str:
    """SHA-256 hex digest of the plaintext key — used as the unique lookup
    column. Not a security boundary on its own (see SCHEMA notes), but the
    high-entropy input means it cannot be reversed from the DB."""
    return hashlib.sha256(plain_key.encode("utf-8")).hexdigest()


def hash_key(plain_key: str) -> str:
    """bcrypt hash of the plaintext key. Stored alongside the lookup hash."""
    # bcrypt's gensalt() default rounds=12 ≈ 250 ms on the production VM —
    # acceptable here because we only run it once per ingest call after
    # the SHA-256 lookup has narrowed down to a single row.
    return bcrypt.hashpw(plain_key.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _row_to_participant(row) -> Participant:
    return Participant(
        id=int(row["id"]),
        steem_account=row["steem_account"],
        display_label=row["display_label"],
        region=row["region"],
        created_at=row["created_at"],
        active=bool(row["active"]),
        note=row["note"],
    )


def create_participant(
    *,
    steem_account: str,
    display_label: str,
    region: Optional[str] = None,
    note: Optional[str] = None,
    db_path: Path | str = DB_PATH,
) -> tuple[Participant, str]:
    """Register a new participant and return (row, plaintext_api_key).

    The plaintext key is the *only* point at which the secret exists in
    full — the caller must hand it to the operator and not log it. Raises
    sqlite3.IntegrityError on duplicate steem_account thanks to the
    UNIQUE constraint, which the API layer translates to HTTP 409.
    """
    plain = generate_api_key()
    now = _utcnow_iso()
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO participants "
            "(steem_account, display_label, region, api_key_lookup, api_key_hash, created_at, active, note) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (
                steem_account,
                display_label,
                region,
                lookup_hash(plain),
                hash_key(plain),
                now,
                note,
            ),
        )
        new_id = int(cur.lastrowid or 0)
        row = conn.execute("SELECT * FROM participants WHERE id=?", (new_id,)).fetchone()
    return _row_to_participant(row), plain


def list_participants(*, db_path: Path | str = DB_PATH) -> list[Participant]:
    """All participants, newest first. Used by the admin list endpoint."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM participants ORDER BY id DESC"
        ).fetchall()
    return [_row_to_participant(r) for r in rows]


def get_participant(participant_id: int, *, db_path: Path | str = DB_PATH) -> Optional[Participant]:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM participants WHERE id=?", (participant_id,)
        ).fetchone()
    return _row_to_participant(row) if row else None


def set_active(participant_id: int, active: bool, *, db_path: Path | str = DB_PATH) -> Optional[Participant]:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE participants SET active=? WHERE id=?",
            (1 if active else 0, participant_id),
        )
    return get_participant(participant_id, db_path=db_path)


def delete_participant(participant_id: int, *, db_path: Path | str = DB_PATH) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM participants WHERE id=?", (participant_id,))
    return cur.rowcount > 0


def verify_api_key(plain_key: str, *, db_path: Path | str = DB_PATH) -> Optional[Participant]:
    """Resolve a plaintext key to its (active) participant or None.

    Returns None for: missing key, malformed key, no matching row,
    inactive row, or bcrypt mismatch. Callers see one outcome — the API
    layer must not leak which of these was the cause, otherwise a
    probe attacker could enumerate active accounts.
    """
    if not plain_key or not plain_key.startswith(KEY_PREFIX):
        return None
    digest = lookup_hash(plain_key)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM participants WHERE api_key_lookup=?", (digest,)
        ).fetchone()
    if row is None or not row["active"]:
        return None
    try:
        ok = bcrypt.checkpw(plain_key.encode("utf-8"), row["api_key_hash"].encode("ascii"))
    except (ValueError, TypeError):
        return None
    return _row_to_participant(row) if ok else None


def measurement_counts(
    *,
    lookback_hours_a: int = 24,
    lookback_hours_b: int = 24 * 7,
    db_path: Path | str = DB_PATH,
) -> dict[str, dict]:
    """Count measurement rows per source_location across two windows.

    Used by /api/v1/sources to show "24 h / 7 d contributions" next to
    each participant. Returns {source_location: {"h24": N, "h7d": M, "last_seen": iso?}}.
    The aggregation is keyed by source_location (which is the participant's
    display_label for external contributors and "contabo-de-1" for the
    primary monitor).
    """
    from database import _utc_iso_minus_minutes  # local import — same module

    cutoff_a = _utc_iso_minus_minutes(lookback_hours_a * 60)
    cutoff_b = _utc_iso_minus_minutes(lookback_hours_b * 60)
    out: dict[str, dict] = {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT source_location, "
            "       SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS h24, "
            "       SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS h7d, "
            "       MAX(timestamp)                                  AS last_seen "
            "  FROM measurements "
            " WHERE source_location IS NOT NULL "
            " GROUP BY source_location",
            (cutoff_a, cutoff_b),
        ).fetchall()
    for r in rows:
        out[r["source_location"]] = {
            "h24": int(r["h24"] or 0),
            "h7d": int(r["h7d"] or 0),
            "last_seen": r["last_seen"],
        }
    return out
