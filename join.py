"""Self-service onboarding for new measurement sources.

Single-step flow: applicant submits steem account + label + region, we
verify the account exists on-chain, create a row in `participants`, and
return the freshly-issued plaintext API key.

There is no memo verification, no pending state, no listener. Account
ownership is not proven by this flow — anyone can register any existing
Steem handle. Operator moderation through /api/v1/admin/participants
(deactivate, delete) is the backstop if a label needs to be cleaned up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx

import config
import participants as participants_mod
from database import DB_PATH


# Steem account-name grammar: 3-16 chars, lowercase letters, digits,
# dots and hyphens; segments cannot start or end with hyphen/dot. The
# loose form below matches what the chain itself accepts and what users
# see in steemit.com URLs.
ACCOUNT_NAME_RE = re.compile(r"^[a-z][a-z0-9.-]{1,14}[a-z0-9]$")


def allowed_regions() -> list[dict]:
    """Region list for the dropdown — id + human label.

    Mirrors `config.REGION_COORDINATES` so adding a region in one place
    propagates to the form automatically.
    """
    return [
        {"id": rid, "label": meta.get("label") or rid}
        for rid, meta in config.REGION_COORDINATES.items()
    ]


# ---------------------------------------------------------------------------
#  Errors. The API layer turns these into HTTP responses.
# ---------------------------------------------------------------------------


class JoinError(Exception):
    """Base class for join-flow failures with a stable status_code field."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
#  Steem account validation.
# ---------------------------------------------------------------------------


def default_account_validator(account: str) -> bool:
    """Return True if the chain knows this account, False otherwise.

    Tries the configured node list one by one until one answers. Treats
    a hard failure (every node times out) as `unknown` and re-raises a
    JoinError so the API layer can return 503 — accepting the join
    blindly would let users register fake accounts.
    """
    payload = {
        "jsonrpc": "2.0",
        "method": "condenser_api.get_accounts",
        "params": [[account]],
        "id": 1,
    }
    last_err: Optional[Exception] = None
    for node in config.load_nodes():
        url = node["url"]
        try:
            with httpx.Client(timeout=config.REQUEST_TIMEOUT_S) as client:
                resp = client.post(url, json=payload)
            if resp.status_code != 200:
                last_err = RuntimeError(f"{url} HTTP {resp.status_code}")
                continue
            body = resp.json()
            if "error" in body:
                last_err = RuntimeError(f"{url} rpc_error: {body['error']}")
                continue
            result = body.get("result") or []
            return len(result) > 0
        except Exception as exc:
            last_err = exc
            continue
    raise JoinError(
        status_code=503,
        code="chain_unreachable",
        message=f"could not reach any Steem node to verify the account "
                f"(last error: {last_err}); please retry shortly",
    )


# ---------------------------------------------------------------------------
#  register — POST /api/v1/join/register backbone.
# ---------------------------------------------------------------------------


@dataclass
class Registration:
    participant: participants_mod.Participant
    api_key: str


def register_participant(
    *,
    steem_account: str,
    display_label: str,
    region: str,
    db_path: Path | str = DB_PATH,
    account_validator: Optional[Callable[[str], bool]] = None,
) -> Registration:
    """Validate input, confirm the account exists on-chain, and create
    the participant row. Returns the freshly-generated plaintext key —
    the API layer is responsible for handing it back to the caller and
    not logging it.

    The chain check runs last so a request with a bad label or an
    already-registered account never costs a network round-trip.
    """
    account = (steem_account or "").strip().lower()
    label = (display_label or "").strip()
    region_id = (region or "").strip()

    if not ACCOUNT_NAME_RE.match(account):
        raise JoinError(400, "invalid_account_name",
                        "steem_account must be 3-16 lowercase letters, digits, dots or hyphens")
    if not label:
        raise JoinError(400, "invalid_label", "display_label must not be empty")
    if len(label) > 64:
        raise JoinError(400, "invalid_label", "display_label must be at most 64 characters")
    valid_regions = {r["id"] for r in allowed_regions()}
    if region_id not in valid_regions:
        raise JoinError(400, "invalid_region",
                        f"region must be one of {sorted(valid_regions)}")

    # Check the participants table before paying for the chain round-trip.
    from database import connect
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM participants WHERE steem_account=?", (account,)
        ).fetchone()
    if row is not None:
        raise JoinError(409, "already_registered",
                        f"@{account} is already registered as a participant")

    validator = account_validator or default_account_validator
    if not validator(account):
        raise JoinError(404, "account_not_found",
                        f"@{account} does not exist on the Steem chain")

    try:
        participant, plain = participants_mod.create_participant(
            steem_account=account,
            display_label=label,
            region=region_id,
            note="self-service join",
            db_path=db_path,
        )
    except Exception as exc:
        # The UNIQUE constraint can still fire if a parallel request
        # snuck in between the check above and the insert. Surface that
        # as 409 so the user sees a stable, recoverable error.
        if "UNIQUE" in str(exc):
            raise JoinError(409, "already_registered",
                            f"@{account} is already registered as a participant")
        raise
    return Registration(participant=participant, api_key=plain)
