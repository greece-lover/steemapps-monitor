"""Ingest pipeline for community-contributed measurements.

The /api/v1/ingest endpoint accepts batches of measurements from the
participant.py script. This module owns the parts that benefit from
unit testing in isolation:

- Token-bucket rate limiter, keyed by participant id
- Per-row validation (timestamp window, node membership, latency bounds,
  success/latency consistency)
- A single normalisation step that turns a request row into the
  Measurement dataclass the database module already knows how to insert.

Why a token bucket and not a fixed window: a participant batches its
last five minutes of polls into one POST, which is 5 × 10 = 50 rows
in a burst. A fixed 700/h window would let one badly-timed retry blow
the budget; the bucket smooths bursts up to its capacity and refills
continuously.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


# -----------------------------------------------------------------
#  Limits — pinned in one place so the participant README and the
#  monitor stay in agreement.
# -----------------------------------------------------------------

# 700 measurements per hour. The expected workload is 10 nodes × 60 s
# = 600/h plus headroom for retries, so this is the headroom not the
# steady-state target.
RATE_LIMIT_PER_HOUR = 700

# Allow a 5-minute participant batch to pass straight through, plus a
# second one as buffer for a retried earlier batch.
RATE_LIMIT_BURST = 100

# A single request never carries more than this many rows. Caps memory
# and prevents a sneaky participant from exhausting the bucket in one
# call. 200 = two minutes of full 100-node fleet, generous.
MAX_BATCH_SIZE = 200

# Timestamp tolerance. Participants buffer for 5 minutes and the network
# adds latency, so we accept up to 15 minutes in the past. The +60 s
# upper bound covers reasonable NTP skew but rejects "future" replays.
MAX_PAST_S = 15 * 60
MAX_FUTURE_S = 60

# Plausibility bounds for the measured latency. Anything outside this
# window is most likely a buggy or hostile reporter and we drop it
# rather than corrupt the rankings.
MIN_LATENCY_MS = 0
MAX_LATENCY_MS = 30_000


# -----------------------------------------------------------------
#  Rate limiter
# -----------------------------------------------------------------


@dataclass
class _Bucket:
    tokens: float
    last_refill_ts: float


class RateLimiter:
    """In-memory token bucket. Single-process safe via a mutex.

    Resetting the process empties the buckets — that is intentional. The
    monitor restarts ~once per deploy; participants can spend a small
    burst right after a restart, which is bounded by RATE_LIMIT_BURST.
    """

    def __init__(self, capacity: int = RATE_LIMIT_BURST, per_hour: int = RATE_LIMIT_PER_HOUR):
        self.capacity = float(capacity)
        self.refill_per_sec = float(per_hour) / 3600.0
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._now = time.monotonic  # injectable for tests

    def consume(self, key: str, cost: int) -> tuple[bool, float]:
        """Try to deduct `cost` tokens for `key`. Returns (granted, remaining)."""
        if cost <= 0:
            return True, self.capacity
        with self._lock:
            now = self._now()
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=self.capacity, last_refill_ts=now)
                self._buckets[key] = b
            elapsed = max(0.0, now - b.last_refill_ts)
            b.tokens = min(self.capacity, b.tokens + elapsed * self.refill_per_sec)
            b.last_refill_ts = now
            if b.tokens < cost:
                return False, b.tokens
            b.tokens -= cost
            return True, b.tokens


# -----------------------------------------------------------------
#  Validation
# -----------------------------------------------------------------


# Reasons returned in the per-row reject list. Stable strings, suitable
# for log-grep and for showing to the operator running the participant
# script. Don't translate — they are part of the API contract.
class RejectReason:
    UNKNOWN_NODE = "unknown_node"
    TIMESTAMP_TOO_OLD = "timestamp_too_old"
    TIMESTAMP_FUTURE = "timestamp_future"
    TIMESTAMP_INVALID = "timestamp_invalid"
    LATENCY_OUT_OF_RANGE = "latency_out_of_range"
    LATENCY_INCONSISTENT = "latency_inconsistent"


def _parse_iso(ts: str) -> Optional[datetime]:
    """Accept either `Z` or `+00:00` suffix; tolerate microseconds."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        # fromisoformat doesn't grok the 'Z' shorthand pre-3.11.
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def validate_row(
    row: dict,
    *,
    known_nodes: set[str],
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Return None if the row is acceptable, else a RejectReason string.

    Rows where success=True must carry latency_ms in range; rows where
    success=False may omit latency_ms (a hard timeout has no measurable
    latency). Rejecting on inconsistency keeps the rankings honest —
    a "successful" tick with no latency would skew p50/p95 calculations.
    """
    if row.get("node_url") not in known_nodes:
        return RejectReason.UNKNOWN_NODE

    parsed = _parse_iso(row.get("timestamp", ""))
    if parsed is None:
        return RejectReason.TIMESTAMP_INVALID
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now_dt = now or datetime.now(timezone.utc)
    delta_s = (now_dt - parsed).total_seconds()
    if delta_s > MAX_PAST_S:
        return RejectReason.TIMESTAMP_TOO_OLD
    if delta_s < -MAX_FUTURE_S:
        return RejectReason.TIMESTAMP_FUTURE

    success = bool(row.get("success"))
    latency = row.get("latency_ms")
    if success:
        if latency is None:
            return RejectReason.LATENCY_INCONSISTENT
        if not isinstance(latency, int) or latency < MIN_LATENCY_MS or latency > MAX_LATENCY_MS:
            return RejectReason.LATENCY_OUT_OF_RANGE
    else:
        # A failed tick with a recorded latency is allowed (e.g. HTTP 500
        # came back at 800 ms) but must still be within bounds.
        if latency is not None:
            if not isinstance(latency, int) or latency < MIN_LATENCY_MS or latency > MAX_LATENCY_MS:
                return RejectReason.LATENCY_OUT_OF_RANGE

    return None


def normalise_timestamp(ts: str) -> str:
    """Pin ingested timestamps to the same `YYYY-MM-DDTHH:MM:SSZ` shape
    the monitor writes, so SQLite's lexicographic comparisons in the
    range queries (see database._utc_iso_minus_minutes) keep working."""
    parsed = _parse_iso(ts) or datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
    return parsed.isoformat().replace("+00:00", "Z")
