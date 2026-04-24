"""Score-algorithm tests.

Each scenario matches one rule from docs/MEASUREMENT-METHODOLOGY.md. The
test file is the ground-truth translation of the prose rules into code — if
these pass and the prose stays in sync, the public methodology claim holds.
"""

from __future__ import annotations

from scoring import (
    calculate_score,
    status_label,
    PENALTY_SLOW,
    PENALTY_VERY_SLOW,
    PENALTY_LAG_MEDIUM,
    PENALTY_LAG_HEAVY,
    PENALTY_HIGH_ERROR_RATE,
    PENALTY_NO_RESPONSE,
)


def _ok(latency_ms=100, block_height=1000):
    return {"success": 1, "latency_ms": latency_ms, "block_height": block_height}


def _fail():
    return {"success": 0, "latency_ms": None, "block_height": None}


def test_fully_healthy_node_scores_100():
    b = calculate_score(
        [_ok()] * 10,
        reference_block=1000,
        current_ok=True,
        current_latency_ms=100,
        current_block_height=1000,
    )
    assert b.score == 100
    assert b.reasons == []


def test_slow_latency_costs_20_points():
    b = calculate_score(
        [_ok(latency_ms=800)],
        reference_block=1000,
        current_ok=True,
        current_latency_ms=800,
        current_block_height=1000,
    )
    assert b.score == 100 - PENALTY_SLOW
    assert any("latency > 500" in r for r in b.reasons)


def test_very_slow_latency_is_cumulative_with_slow():
    # 2500 ms triggers both bands: -20 for >500, -50 additionally for >2000.
    b = calculate_score(
        [_ok(latency_ms=2500)],
        reference_block=1000,
        current_ok=True,
        current_latency_ms=2500,
        current_block_height=1000,
    )
    assert b.score == 100 - PENALTY_SLOW - PENALTY_VERY_SLOW
    assert any("500" in r for r in b.reasons)
    assert any("2000" in r for r in b.reasons)


def test_medium_block_lag_costs_30_points():
    b = calculate_score(
        [_ok()],
        reference_block=1005,  # 5 behind → >3, not >10
        current_ok=True,
        current_latency_ms=100,
        current_block_height=1000,
    )
    assert b.score == 100 - PENALTY_LAG_MEDIUM


def test_heavy_block_lag_is_cumulative_with_medium():
    b = calculate_score(
        [_ok()],
        reference_block=1020,  # 20 behind → triggers both rules
        current_ok=True,
        current_latency_ms=100,
        current_block_height=1000,
    )
    assert b.score == 100 - PENALTY_LAG_MEDIUM - PENALTY_LAG_HEAVY


def test_no_response_collapses_to_zero_regardless_of_history():
    b = calculate_score(
        [_ok()] * 5,
        reference_block=1000,
        current_ok=False,
        current_latency_ms=None,
        current_block_height=None,
    )
    # 100 - 100 = 0; no further penalties applied.
    assert b.score == 0
    assert b.reasons == [f"no response this tick (−{PENALTY_NO_RESPONSE})"]


def test_high_error_rate_triggers_penalty():
    # 5 fails out of 10 = 50 %, well over the 20 % threshold.
    window = [_fail()] * 5 + [_ok()] * 5
    b = calculate_score(
        window,
        reference_block=1000,
        current_ok=True,
        current_latency_ms=100,
        current_block_height=1000,
    )
    assert b.score == 100 - PENALTY_HIGH_ERROR_RATE
    assert any("error rate" in r for r in b.reasons)


def test_error_rate_at_20_percent_does_not_trigger():
    # Exactly 20 % — the rule says "> 20 %", so 20 % passes.
    window = [_fail()] * 2 + [_ok()] * 8
    b = calculate_score(
        window,
        reference_block=1000,
        current_ok=True,
        current_latency_ms=100,
        current_block_height=1000,
    )
    assert b.score == 100


def test_score_floors_at_zero():
    # Pile on every penalty; result still can't dip below 0.
    b = calculate_score(
        [_fail()] * 20,
        reference_block=1020,
        current_ok=True,
        current_latency_ms=2500,
        current_block_height=1000,
    )
    assert b.score == 0


def test_block_lag_rule_skipped_when_no_reference():
    # If all nodes failed this tick, we have no chain-height reference;
    # block-lag rules must not fire.
    b = calculate_score(
        [_ok()],
        reference_block=None,
        current_ok=True,
        current_latency_ms=100,
        current_block_height=1000,
    )
    assert b.score == 100


def test_status_label_reflects_score_and_liveness():
    assert status_label(100, True) == "ok"
    assert status_label(60, True) == "degraded"
    assert status_label(30, True) == "down"
    # Not-ok always maps to down regardless of score.
    assert status_label(100, False) == "down"
