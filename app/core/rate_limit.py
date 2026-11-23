"""Sliding-window rate limiter (ARQ-05).

Moved out of ``app/api/v1/auth.py`` so the limiter is a module of its own:

* ``RateLimiter.check(key)`` raises ``RateLimited(retry_after)`` instead of an
  ``HTTPException``; ERR-03 turns ``retry_after`` into the ``Retry-After``
  header and SEG-02 extends this class (failed attempts only, per-email
  limit) instead of ``auth.py``.
* The clock is injectable, so tests move time forward without ``sleep``.
* Memory is bounded: buckets whose window has passed are deleted, and the
  number of tracked keys never exceeds ``max_keys``.
* There is no module-level state. ``create_app`` builds the limiters and
  keeps them in ``app.state`` (ARQ-01), so two apps never share counters.

``check`` is synchronous and has no ``await``, so on a single event loop one
call can never interleave with another. The state is per process: with
several uvicorn workers (PERF-03) every worker keeps its own counters and the
effective limit is multiplied by the number of workers.
"""

import math
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Final

from app.core.errors import RateLimited

# Sliding-window settings of the auth endpoints, per client IP.
RATE_LIMIT_WINDOW_SECONDS: Final[float] = 60.0
MAX_LOGIN_ATTEMPTS_PER_WINDOW: Final[int] = 10
MAX_REGISTER_ATTEMPTS_PER_WINDOW: Final[int] = 5
MAX_EMAIL_VALIDATION_ATTEMPTS_PER_WINDOW: Final[int] = 15

# Upper bound for the tracked keys of one limiter. Each key keeps at most
# ``max_attempts`` floats, so memory stays bounded however many distinct
# clients (or forged keys) show up.
DEFAULT_MAX_KEYS: Final[int] = 10_000

# Returns the current time in seconds. It must be monotonic.
Clock = Callable[[], float]


class RateLimiter:
    """
    Allow at most ``max_attempts`` calls per key in a sliding window.

    Every accepted call is recorded; a rejected call is not, so a blocked
    client is released ``window_seconds`` after its oldest recorded call.

    Args:
        max_attempts (int): Calls allowed per key inside the window.
        window_seconds (float): Length of the sliding window.
        max_keys (int): Maximum number of keys tracked at once. When it is
            reached and no bucket has expired, the least recently used key is
            dropped to make room.
        clock (Clock): Time source. Tests pass a fake one.
    """

    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
        max_keys: int = DEFAULT_MAX_KEYS,
        clock: Clock = time.monotonic,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if max_keys < 1:
            raise ValueError("max_keys must be at least 1")
        self.max_attempts: Final[int] = max_attempts
        self.window_seconds: Final[float] = window_seconds
        self.max_keys: Final[int] = max_keys
        self._clock: Final[Clock] = clock
        # Ordered from least to most recently used: a key moves to the end
        # every time a call is accepted, so expired buckets pile up in front.
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()

    def __len__(self) -> int:
        """Number of keys currently tracked."""
        return len(self._buckets)

    def check(self, key: str) -> None:
        """
        Record one call for ``key`` or reject it.

        Raises:
            RateLimited: If ``key`` already used its ``max_attempts`` in the
                window. ``retry_after`` is the whole seconds (at least 1)
                until the oldest recorded call leaves the window.
        """
        now: float = self._clock()
        self._drop_expired(now)

        bucket: deque[float] | None = self._buckets.get(key)
        if bucket is not None:
            while bucket and self._expired(bucket[0], now):
                bucket.popleft()
            if len(bucket) >= self.max_attempts:
                retry_after: float = bucket[0] + self.window_seconds - now
                raise RateLimited(max(1, math.ceil(retry_after)))
        else:
            if len(self._buckets) >= self.max_keys:
                self._buckets.popitem(last=False)
            bucket = self._buckets[key] = deque()

        bucket.append(now)
        self._buckets.move_to_end(key)

    def _expired(self, timestamp: float, now: float) -> bool:
        """A call leaves the window exactly ``window_seconds`` after it."""
        return now - timestamp >= self.window_seconds

    def _drop_expired(self, now: float) -> None:
        """
        Delete the buckets whose newest call already left the window.

        Keys are ordered by their last accepted call, so it is enough to look
        at the front: the work is amortized O(1) per ``check``. A key that
        never comes back is therefore freed by the next call of any key.
        """
        while self._buckets:
            oldest_key, bucket = next(iter(self._buckets.items()))
            if bucket and not self._expired(bucket[-1], now):
                return
            del self._buckets[oldest_key]