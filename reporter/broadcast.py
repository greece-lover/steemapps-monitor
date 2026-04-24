"""Steem broadcast wrapper — beem in prod, stdout in dev.

The module is deliberately small. It owns exactly three concerns:

1. Lazily import beem, so the dev path (and the test suite) can run
   without beem installed at all.
2. Enforce the broadcast order: `custom_json` first, then `comment`. The
   post body references the `custom_json` transaction, so the comment can
   only be built after the first broadcast has returned its tx hash.
3. Retry transient failures (network, RPC) with a fixed back-off.
   Permanent failures (duplicate permlink, signature rejected) are raised
   immediately — retrying them would just log the same error three times.

Production mode requires a posting key in the environment; dev mode needs
nothing and prints the post to stdout instead of touching the chain.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional

import logger as logger_mod

from reporter.config import ReporterConfig
from reporter.template import ChainReference, RenderedPost


log = logger_mod.get("reporter.broadcast")


# Free-form error substrings that we treat as permanent. beem does not
# expose a clean exception hierarchy for "duplicate permlink" vs "RPC
# unreachable", so we fall back to substring matching. False negatives
# here mean we retry something we shouldn't (wastes three minutes), which
# is much better than false positives (silently dropping a real retryable
# failure).
_PERMANENT_ERROR_HINTS = (
    "duplicate",             # duplicate permlink / duplicate transaction
    "invalid signature",
    "missing required posting authority",
    "unauthorized",
    "insufficient rc",       # out of resource credits — waiting 60 s won't help
)


class BroadcastError(RuntimeError):
    """Raised when the broadcast attempts are exhausted."""


@dataclass(frozen=True)
class BroadcastResult:
    tx_hash: str
    block_num: int


def _is_permanent(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(hint in text for hint in _PERMANENT_ERROR_HINTS)


def _retry(cfg: ReporterConfig, op_label: str, fn):
    """Run `fn` with retry — returns fn's value or raises BroadcastError."""
    last_exc: Optional[BaseException] = None
    for attempt in range(1, cfg.broadcast_retry_count + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if _is_permanent(exc):
                log.error(
                    "broadcast %s failed permanently (attempt %d): %s",
                    op_label, attempt, exc,
                )
                raise BroadcastError(f"{op_label} permanent failure: {exc}") from exc
            log.warning(
                "broadcast %s failed (attempt %d/%d): %s",
                op_label, attempt, cfg.broadcast_retry_count, exc,
            )
            if attempt < cfg.broadcast_retry_count:
                time.sleep(cfg.broadcast_retry_sleep_s)
    raise BroadcastError(
        f"{op_label} exhausted {cfg.broadcast_retry_count} attempts"
    ) from last_exc


def _build_steem(cfg: ReporterConfig):
    """Import beem lazily and construct a Steem client.

    Keeping the import inside the function means dev-mode and the test
    suite don't need beem on the path. Production installs pull it in via
    requirements-reporter.txt. The posting-key guard runs before the
    import so a missing key gives a clear BroadcastError instead of a
    confusing ImportError on a machine without beem.
    """
    if not cfg.posting_key:
        raise BroadcastError(
            "STEEMAPPS_REPORTER_POSTING_KEY is empty — refusing to broadcast"
        )
    from beem import Steem  # type: ignore[import-not-found]
    return Steem(keys=[cfg.posting_key])


def _broadcast_custom_json_real(cfg: ReporterConfig, payload: dict) -> BroadcastResult:
    steem = _build_steem(cfg)
    result = steem.custom_json(
        id=cfg.custom_json_id,
        json_data=payload,
        required_posting_auths=[cfg.account],
    )
    return _extract_tx_info(result)


def _broadcast_comment_real(cfg: ReporterConfig, post: RenderedPost) -> BroadcastResult:
    steem = _build_steem(cfg)
    result = steem.post(
        title=post.title,
        body=post.body,
        author=cfg.account,
        permlink=post.permlink,
        tags=post.json_metadata.get("tags", []),
        json_metadata=post.json_metadata,
    )
    return _extract_tx_info(result)


def _extract_tx_info(result: Any) -> BroadcastResult:
    """Pull tx id and block number out of beem's broadcast return value.

    beem's return shape varies by version and operation; we try the
    common fields and fall back to stringified "unknown" rather than
    raising — the broadcast itself succeeded, the report just won't
    contain a precise chain pointer.
    """
    if isinstance(result, dict):
        tx_hash = (
            result.get("trx_id")
            or result.get("id")
            or result.get("transaction_id")
            or "unknown"
        )
        block_num = int(result.get("block_num") or result.get("ref_block_num") or 0)
        return BroadcastResult(tx_hash=str(tx_hash), block_num=block_num)
    return BroadcastResult(tx_hash="unknown", block_num=0)


def broadcast_custom_json(cfg: ReporterConfig, payload: dict) -> BroadcastResult:
    """Send the raw-data `custom_json`. Dev mode prints and returns a fake ref."""
    if cfg.is_dev:
        log.info("dev mode: would broadcast custom_json id=%s", cfg.custom_json_id)
        log.info("dev mode: payload (%d bytes) follows", len(json.dumps(payload)))
        print("---- DRY-RUN: custom_json ----")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("---- END DRY-RUN: custom_json ----")
        return BroadcastResult(tx_hash="dry-run-custom-json", block_num=0)
    return _retry(cfg, "custom_json", lambda: _broadcast_custom_json_real(cfg, payload))


def broadcast_comment(cfg: ReporterConfig, post: RenderedPost) -> BroadcastResult:
    """Send the comment. Dev mode prints and returns a fake ref."""
    if cfg.is_dev:
        log.info("dev mode: would broadcast comment permlink=%s", post.permlink)
        print("---- DRY-RUN: comment ----")
        print(f"Title: {post.title}")
        print(f"Permlink: {post.permlink}")
        print(f"Author: {cfg.account}")
        print(f"Tags: {post.json_metadata.get('tags')}")
        print()
        print(post.body)
        print("---- END DRY-RUN: comment ----")
        return BroadcastResult(tx_hash="dry-run-comment", block_num=0)
    return _retry(cfg, "comment", lambda: _broadcast_comment_real(cfg, post))


def to_chain_reference(result: BroadcastResult) -> ChainReference:
    return ChainReference(tx_hash=result.tx_hash, block_num=result.block_num)
