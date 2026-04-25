"""Broadcast-layer tests — dev mode + retry policy.

beem is deliberately *not* imported here. Prod-mode tests would need the
real library (and a test net), which is out of scope for Phase 5's
dry-run deliverable. What we can test without beem is:

- dev mode returns fake tx refs and prints nothing to the chain;
- the retry helper retries transient failures and surfaces permanent
  ones immediately;
- the pair of broadcasts happens in the right order with the chain
  reference feeding the second one.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from reporter import broadcast, template
from reporter.config import MODE_DEV, ReporterConfig


def _cfg(mode: str = MODE_DEV, retries: int = 3, retry_sleep_s: int = 0) -> ReporterConfig:
    from pathlib import Path
    return ReporterConfig(
        mode=mode,
        account="steem-api-health",
        posting_key="dev-placeholder" if mode != MODE_DEV else None,
        custom_json_id="steemapps_api_stats_daily",
        tags=["steem", "api", "monitoring"],
        app_name="steemapps-monitor/test",
        dashboard_url="https://api.steemapps.com",
        methodology_url="https://example.test/METH.md",
        repo_url="https://github.com/greece-lover/steemapps-monitor",
        witness_url="https://steemitwallet.com/~witnesses",
        db_path=Path("test.sqlite"),
        broadcast_retry_count=retries,
        broadcast_retry_sleep_s=retry_sleep_s,
        image_dir=Path("test-reports"),
        image_url_base=None,
    )


def test_dev_mode_custom_json_returns_dry_run_ref(capsys):
    cfg = _cfg()
    result = broadcast.broadcast_custom_json(cfg, {"hello": "world"})
    assert result.tx_hash == "dry-run-custom-json"
    assert result.block_num == 0
    # Stdout should contain the payload so a human can eyeball it.
    out = capsys.readouterr().out
    assert '"hello": "world"' in out


def test_dev_mode_comment_returns_dry_run_ref(capsys):
    cfg = _cfg()
    post = template.RenderedPost(
        title="T", permlink="p", body="B",
        json_metadata={"tags": ["steem"]},
    )
    result = broadcast.broadcast_comment(cfg, post)
    assert result.tx_hash == "dry-run-comment"
    out = capsys.readouterr().out
    assert "Title: T" in out
    assert "Permlink: p" in out


def test_retry_surfaces_permanent_errors_immediately():
    cfg = _cfg(mode="prod", retries=3, retry_sleep_s=0)
    attempts = {"n": 0}

    def _op():
        attempts["n"] += 1
        raise RuntimeError("duplicate transaction detected")

    with pytest.raises(broadcast.BroadcastError):
        broadcast._retry(cfg, "custom_json", _op)
    # Permanent errors should not loop — exactly one attempt.
    assert attempts["n"] == 1


def test_retry_loops_on_transient_errors_then_raises():
    cfg = _cfg(mode="prod", retries=3, retry_sleep_s=0)
    attempts = {"n": 0}

    def _op():
        attempts["n"] += 1
        raise RuntimeError("connection reset by peer")

    with pytest.raises(broadcast.BroadcastError):
        broadcast._retry(cfg, "custom_json", _op)
    assert attempts["n"] == 3  # exactly cfg.broadcast_retry_count attempts


def test_retry_succeeds_on_third_attempt():
    cfg = _cfg(mode="prod", retries=3, retry_sleep_s=0)
    attempts = {"n": 0}

    def _op():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("connection reset")
        return "ok"

    assert broadcast._retry(cfg, "custom_json", _op) == "ok"
    assert attempts["n"] == 3


def test_is_permanent_matches_known_strings():
    assert broadcast._is_permanent(RuntimeError("Duplicate transaction"))
    assert broadcast._is_permanent(RuntimeError("Invalid signature"))
    assert broadcast._is_permanent(RuntimeError("INSUFFICIENT RC — try again later"))
    # Transient errors must not be classed as permanent.
    assert not broadcast._is_permanent(RuntimeError("connection reset"))
    assert not broadcast._is_permanent(RuntimeError("read timeout"))
    assert not broadcast._is_permanent(RuntimeError("503 service unavailable"))


def test_prod_mode_refuses_empty_posting_key():
    # _build_steem is invoked inside _broadcast_custom_json_real via _retry;
    # with no beem installed and no key present, we want the guard to fire
    # before the import, not a beem ImportError.
    cfg = _cfg(mode="prod")
    from dataclasses import replace
    cfg = replace(cfg, posting_key=None)

    with patch.object(broadcast, "_retry", side_effect=lambda c, label, fn: fn()):
        with pytest.raises(broadcast.BroadcastError) as ei:
            broadcast.broadcast_custom_json(cfg, {"k": "v"})
    assert "POSTING_KEY" in str(ei.value)
