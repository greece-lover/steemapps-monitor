"""In-process TTL cache — no external dependency.

Drop-in decorator for any pure-read function whose result can be reused
for a few seconds. The dashboard hits the API once per second across
clients and panels, so even a 10-second TTL collapses an order of
magnitude of SQLite work. We deliberately do not use LRU eviction: the
dashboard's call set is small (< 50 distinct cache keys) and each entry
expires on its own schedule.

Not thread-safe in the strict sense — the single-process FastAPI event
loop serialises access so the window for a race is nanoseconds, and at
worst two clients would each compute the same value once. That tradeoff
is fine for a cache, not fine for a correctness primitive.
"""

from __future__ import annotations

import functools
import time
from typing import Callable


def ttl_cache(seconds: float) -> Callable:
    """Memoise a function's results for `seconds`, keyed by (args, kwargs).

    Keys are built from args and sorted kwargs-items; both must be
    hashable. Decorator exposes `cache_clear()` and `cache_info()` on the
    wrapped function for tests and for the /api/v1/health endpoint to
    report cache state later if we decide to.
    """
    def decorator(fn):
        store: dict = {}

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            entry = store.get(key)
            if entry is not None and entry[0] > now:
                return entry[1]
            value = fn(*args, **kwargs)
            store[key] = (now + seconds, value)
            return value

        def cache_clear():
            store.clear()

        def cache_info():
            return {"size": len(store), "ttl_s": seconds}

        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        wrapper.cache_info = cache_info    # type: ignore[attr-defined]
        return wrapper

    return decorator
