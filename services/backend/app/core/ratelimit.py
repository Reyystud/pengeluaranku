"""In-memory sliding-window rate limiter (PRD 13.1.6 in-memory fallback; Redis is optional).

State is per process: with several instances the effective limit is multiplied. Documented in
DECISIONS; the Redis-backed implementation is a drop-in for the same ``RateLimiter`` interface.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def key(scope: str, value: str) -> str:
        """Keys are hashed so raw emails never sit in memory dumps or logs."""
        return f"{scope}:{hashlib.sha256(value.encode()).hexdigest()[:24]}"

    def _prune(self, key: str, window: float) -> deque[float]:
        events = self._events[key]
        cutoff = self._clock() - window
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def retry_after(self, key: str, limit: int, window: float) -> int:
        """Seconds until a slot frees up, or 0 if the key is under ``limit``."""
        with self._lock:
            events = self._prune(key, window)
            if len(events) < limit:
                return 0
            return max(1, int(events[0] + window - self._clock()) + 1)

    def record(self, key: str, window: float) -> None:
        with self._lock:
            self._prune(key, window).append(self._clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
