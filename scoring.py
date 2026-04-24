"""Health-score calculation.

Implements the rules pinned in docs/MEASUREMENT-METHODOLOGY.md (methodology
version `mv1`). The function is deliberately pure: it takes a window of
recent measurements plus a chain-wide reference block height and returns a
score and a breakdown. All I/O lives in api.py / monitor.py so tests can
exercise the algorithm with synthetic inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


# Rule thresholds — kept as module-level constants so they're trivially
# greppable from either the docs or a code review.
LATENCY_SLOW_MS = 500
LATENCY_VERY_SLOW_MS = 2000
BLOCK_LAG_MEDIUM = 3
BLOCK_LAG_HEAVY = 10
ERROR_RATE_THRESHOLD = 0.20  # 20 %

PENALTY_SLOW = 20
PENALTY_VERY_SLOW = 50
PENALTY_LAG_MEDIUM = 30
PENALTY_LAG_HEAVY = 70
PENALTY_HIGH_ERROR_RATE = 40
PENALTY_NO_RESPONSE = 100


@dataclass
class ScoreBreakdown:
    score: int
    reasons: list[str] = field(default_factory=list)


def calculate_score(
    measurements: Iterable[dict],
    reference_block: Optional[int],
    *,
    current_ok: Optional[bool] = None,
    current_latency_ms: Optional[int] = None,
    current_block_height: Optional[int] = None,
) -> ScoreBreakdown:
    """Compute a 0..100 health score for one node.

    Parameters
    ----------
    measurements
        Recent measurements for this node, ordered newest-first. Used only
        to compute the error rate across the lookback window.
    reference_block
        The current chain head — typically `max(block_height)` across every
        node's most-recent successful tick. None if no node succeeded this
        tick; block-lag rules are then skipped.
    current_ok
        Whether the *most recent* measurement for this node was a success.
        If None, it is inferred from `measurements[0]`.
    current_latency_ms
        Latency of the most recent measurement. None if the node did not
        respond at all this tick.
    current_block_height
        Head block reported by the most recent measurement. None if the
        response couldn't be parsed.
    """
    measurements = list(measurements)
    if current_ok is None:
        current_ok = bool(measurements[0]["success"]) if measurements else False
    if current_latency_ms is None and measurements:
        current_latency_ms = measurements[0].get("latency_ms")
    if current_block_height is None and measurements:
        current_block_height = measurements[0].get("block_height")

    score = 100
    reasons: list[str] = []

    # Rule 6: no response this tick — collapse immediately, do not apply
    # the other penalties (the latency / block values don't exist).
    if not current_ok:
        score -= PENALTY_NO_RESPONSE
        reasons.append(f"no response this tick (−{PENALTY_NO_RESPONSE})")
        return ScoreBreakdown(score=max(score, 0), reasons=reasons)

    # Rule 1 + 2: latency bands. The rules are additive — a 3-second
    # response pays both the slow and very-slow penalties.
    if current_latency_ms is not None:
        if current_latency_ms > LATENCY_SLOW_MS:
            score -= PENALTY_SLOW
            reasons.append(f"latency > {LATENCY_SLOW_MS} ms (−{PENALTY_SLOW})")
        if current_latency_ms > LATENCY_VERY_SLOW_MS:
            score -= PENALTY_VERY_SLOW
            reasons.append(f"latency > {LATENCY_VERY_SLOW_MS} ms (−{PENALTY_VERY_SLOW})")

    # Rule 3 + 4: block lag, again additive.
    if reference_block is not None and current_block_height is not None:
        lag = reference_block - current_block_height
        if lag > BLOCK_LAG_MEDIUM:
            score -= PENALTY_LAG_MEDIUM
            reasons.append(f"block lag > {BLOCK_LAG_MEDIUM} (−{PENALTY_LAG_MEDIUM})")
        if lag > BLOCK_LAG_HEAVY:
            score -= PENALTY_LAG_HEAVY
            reasons.append(f"block lag > {BLOCK_LAG_HEAVY} (−{PENALTY_LAG_HEAVY})")

    # Rule 5: recent error rate above 20 % across the lookback window.
    if measurements:
        total = len(measurements)
        failed = sum(1 for m in measurements if not m["success"])
        err_rate = failed / total if total else 0.0
        if err_rate > ERROR_RATE_THRESHOLD:
            score -= PENALTY_HIGH_ERROR_RATE
            reasons.append(
                f"error rate {err_rate:.0%} > {ERROR_RATE_THRESHOLD:.0%} over last "
                f"{total} ticks (−{PENALTY_HIGH_ERROR_RATE})"
            )

    return ScoreBreakdown(score=max(score, 0), reasons=reasons)


def status_label(score: int, current_ok: bool) -> str:
    """Map numeric score to the string used by the public `status` field.

    Kept next to `calculate_score` so both pieces of derivation live in one
    place and any policy shift only touches this file.
    """
    if not current_ok:
        return "down"
    if score >= 80:
        return "ok"
    if score >= 40:
        return "degraded"
    return "down"
