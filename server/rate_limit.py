"""Per-caller rate limiting for state-changing requests.

A token bucket keyed by principal (or client address when anonymous),
applied to POST/PUT/DELETE so a runaway client or a stolen token cannot
exhaust the backend or the model budget.

Scope, stated honestly: the bucket lives in this process. It protects a
single instance, which is the supported deployment today. Multi-instance
deployments need a shared store (Redis or a database table) — tracked in
the roadmap, not silently assumed here.
"""

import threading
import time

WRITE_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


class RateLimiter:
    def __init__(self, limit=120, window_seconds=60, clock=time.monotonic):
        self.limit = max(1, int(limit))
        self.window = max(1, int(window_seconds))
        self._clock = clock
        self._buckets = {}
        self._lock = threading.Lock()

    def check(self, key):
        """Return (allowed, remaining, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            tokens, updated = self._buckets.get(key, (float(self.limit), now))
            # Refill continuously rather than in fixed windows, so a
            # caller cannot burst twice across a window boundary.
            tokens = min(
                float(self.limit),
                tokens + (now - updated) * (self.limit / self.window),
            )
            if tokens < 1.0:
                retry_after = max(1, int((1.0 - tokens) * (self.window / self.limit)) + 1)
                self._buckets[key] = (tokens, now)
                return False, 0, retry_after
            tokens -= 1.0
            self._buckets[key] = (tokens, now)
            return True, int(tokens), 0
