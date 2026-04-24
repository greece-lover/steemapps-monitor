"""One-shot: set the Steem `json_metadata` profile for @steem-api-health.

Runs on the production server (or anywhere beem is installed). Reads the
active key from a temporary env file, broadcasts a single `account_update`
operation, then shreds the env file so the key is gone before the script
exits.

Usage:

    # Dry-run — render the payload, do not touch the chain, do not read
    # the key file. Safe to run without staging the key.
    python3 setup_profile.py --dry-run

    # Real run — requires the active key at the env-file path. The env
    # file is shredded and unlinked unconditionally on exit.
    python3 setup_profile.py

The env file default is /tmp/steem-api-health-active.env and must contain:

    STEEMAPPS_PROFILE_ACTIVE_KEY=5Jxxx...

Nothing else. Comments and blank lines are allowed. `chmod 600` before
running (the script checks and refuses to proceed if the file is
world-readable).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional


ACCOUNT = "steem-api-health"
MAINTAINER = "greece-lover"
WEBSITE = "https://api.steemapps.com"

PROFILE_METADATA = {
    "profile": {
        "name": "Steem API Health",
        "about": (
            "Automated monitoring of public Steem API nodes. Daily uptime "
            "reports, latency metrics, and regional analysis. Operated by "
            f"@{MAINTAINER} as an independent infrastructure project."
        ),
        "website": WEBSITE,
        "location": "",
        "profile_image": f"{WEBSITE}/profile.png",
        "cover_image": f"{WEBSITE}/cover.png",
        "version": 2,
    }
}

DEFAULT_ENV_FILE = Path("/tmp/steem-api-health-active.env")
KEY_VAR = "STEEMAPPS_PROFILE_ACTIVE_KEY"


def _log(msg: str) -> None:
    # Stdout-only, prefix so journald parses cleanly if anyone captures this.
    print(f"[setup_profile] {msg}", flush=True)


def _read_env_key(env_file: Path) -> str:
    """Parse the temporary env file and return the active key.

    The file must be readable only by its owner (mode bits 0o077 clear).
    A world-readable key file is a red flag — somebody else can see it —
    so refuse instead of proceeding.
    """
    if not env_file.exists():
        raise SystemExit(
            f"env file not found at {env_file}. Stage the active key on "
            f"the server via SSH before running the real broadcast."
        )
    st = env_file.stat()
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SystemExit(
            f"env file {env_file} is group- or world-accessible. "
            f"`chmod 600 {env_file}` and retry."
        )
    key: Optional[str] = None
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == KEY_VAR:
            key = value.strip().strip('"').strip("'")
    if not key:
        raise SystemExit(f"{KEY_VAR} not set in {env_file}")
    return key


def _key_fingerprint(key: str) -> str:
    """Stable short fingerprint of the key for log correlation.

    Logging the raw key is unsafe; logging *nothing* makes it impossible
    to confirm later that the expected key was used. A SHA-256 prefix is
    a standard compromise.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _shred_env_file(env_file: Path) -> None:
    """Overwrite + unlink. Uses `shred` if available, else a Python fallback.

    The fallback writes one pass of zero-bytes and unlinks; on a modern
    SSD the difference between one and many passes is largely symbolic,
    but `shred -u` is the canonical tool on Ubuntu so we prefer it.
    """
    if not env_file.exists():
        _log(f"env file {env_file} already gone — nothing to shred")
        return
    shred = shutil.which("shred")
    if shred:
        try:
            subprocess.run(
                [shred, "-u", "-n", "3", "-z", str(env_file)],
                check=True, capture_output=True, text=True,
            )
            _log(f"shredded and unlinked {env_file}")
            return
        except subprocess.CalledProcessError as exc:
            _log(f"shred failed ({exc.returncode}): {exc.stderr.strip()} — falling back to Python zero-pass")
    # Python fallback.
    try:
        size = env_file.stat().st_size
        with open(env_file, "r+b") as fh:
            fh.write(b"\x00" * max(size, 1))
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        _log(f"zero-pass failed: {exc}")
    try:
        env_file.unlink()
        _log(f"unlinked {env_file} (Python fallback)")
    except OSError as exc:
        _log(f"unlink failed: {exc}")


STEEM_RPC_NODES = [
    "https://api.steemit.com",
    "https://api.justyy.com",
    "https://steemd.steemworld.org",
]


def _broadcast_account_update(active_key: str, metadata: dict) -> str:
    """Broadcast `account_update` with the new `json_metadata`.

    Returns the trx_id from beem's response. `account_update` needs the
    active authority; posting authority is not enough for a profile
    change, which is why this script reads a separate env var.

    beem 0.24.26's default node list was sometimes Hive-leaning and could
    return "account does not exist" for Steem accounts. Passing
    `node=[...]` explicitly with the Steem RPC endpoints the monitor
    already trusts avoids that trap — these are the same URLs that
    populate the daily report.
    """
    from beem import Steem  # imported lazily so --dry-run does not need beem
    from beem.account import Account

    stm = Steem(node=STEEM_RPC_NODES, keys=[active_key])
    account = Account(ACCOUNT, blockchain_instance=stm)
    # `update_account_metadata` writes the classic `json_metadata` slot
    # via the `account_update` op — what steemit.com reads for the
    # profile card.
    result = account.update_account_metadata(metadata)
    if isinstance(result, dict):
        return str(result.get("trx_id") or result.get("id") or "unknown")
    # Some beem versions return a TransactionTrx object with a `.trx_id`.
    return str(getattr(result, "trx_id", "unknown"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Set @steem-api-health profile metadata.")
    ap.add_argument("--dry-run", action="store_true",
                    help="render the payload and exit; do not read the key, do not broadcast")
    ap.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE,
                    help=f"path to the env file containing {KEY_VAR} (default: {DEFAULT_ENV_FILE})")
    args = ap.parse_args(argv)

    _log(f"account=@{ACCOUNT}")
    _log(f"profile_image={PROFILE_METADATA['profile']['profile_image']}")
    _log(f"cover_image={PROFILE_METADATA['profile']['cover_image']}")
    _log(f"website={PROFILE_METADATA['profile']['website']}")

    rendered = json.dumps(PROFILE_METADATA, ensure_ascii=False, indent=2)
    print("---- json_metadata ----")
    print(rendered)
    print("---- end json_metadata ----")

    if args.dry_run:
        _log("dry-run: no key read, no broadcast, env file untouched")
        return 0

    # Real run — env file required, shredded unconditionally on exit.
    try:
        active_key = _read_env_key(args.env_file)
        _log(f"loaded active key, sha256 prefix = {_key_fingerprint(active_key)}")
        try:
            trx_id = _broadcast_account_update(active_key, PROFILE_METADATA)
        finally:
            # Zero the local reference before going further. Does not
            # guarantee removal from memory (Python strings are
            # immutable and may be interned), but shortens the window.
            active_key = "X" * len(active_key)
            del active_key
        _log(f"broadcast complete, trx_id={trx_id}")
        print(f"---- result ----")
        print(f"account=@{ACCOUNT}")
        print(f"trx_id={trx_id}")
        print(f"profile_url=https://steemit.com/@{ACCOUNT}")
        print(f"---- end result ----")
        return 0
    finally:
        _shred_env_file(args.env_file)


if __name__ == "__main__":
    sys.exit(main())
