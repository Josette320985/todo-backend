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

from app.core.emails import normalize_email
from app.core.errors import RateLimited

# Sliding-window settings of the auth endpoints, per client IP.
RATE_LIMIT_WINDOW_SECONDS: Final[float] = 60.0
# Failed logins allowed per IP, and per IP + email (SEG-02). The second one is
# lower on purpose: it stops a guessing run against one account before the
# whole IP budget is spent.
MAX_LOGIN_ATTEMPTS_PER_WINDOW: Final[int] = 10
MAX_LOGIN_ATTEMPTS_PER_EMAIL_PER_WINDOW: Final[int] = 5
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

    * ``RateLimiter.check(key)`` raises ``RateLimited(retry_after)`` instead of an
    ``HTTPException``; ERR-03 turns ``retry_after`` into the ``Retry-After``
    header.
    * ``LoginRateLimiter`` (SEG-02) counts only the failed logins, per IP and per
    IP + email. It lives here and not in ``auth.py``.
    
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

    def forgive(self, key: str) -> None:
        """
        Remove the most recent call recorded for ``key``, if any.

        ``check`` records the call before the work it protects runs, so
        concurrent requests cannot all slip past the limit. Callers that only
        want to count failures forgive the call once the work succeeded.
        The key keeps its place in the eviction order: it is freed when it
        reaches the front or on its next ``check``.
        """
        bucket: deque[float] | None = self._buckets.get(key)
        if bucket is None:
            return
        if bucket:
            bucket.pop()
        if not bucket:
            del self._buckets[key]

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


# Longest email kept in a key. The nginx body limit already bounds the request;
# this bounds what one forged username can cost in memory.
_MAX_EMAIL_KEY_LENGTH: Final[int] = 320


def _email_key(email: str) -> str:
    """Canonical form of a submitted username, so ``A@x.com`` and ``a@x.com`` share a counter."""
    try:
        canonical: str = normalize_email(email)
    except ValueError:
        canonical = email.strip().lower()
    return canonical[:_MAX_EMAIL_KEY_LENGTH]


class LoginRateLimiter:
    """
    Limit failed logins per IP and per IP + email (SEG-02).

    ``check`` records the attempt before the credentials are verified and
    ``succeeded`` forgives it afterwards, so only failures stay counted while
    parallel guesses still hit the limit. A blocked attempt is not recorded in
    either counter.

    The per-email counter is keyed by the pair (IP, email) and not by the email
    alone: otherwise anyone could lock a victim out of their account from
    anywhere by failing logins on their email.

    Args:
        per_ip (RateLimiter): Failed logins allowed per client IP.
        per_pair (RateLimiter): Failed logins allowed per IP + email.
    """

    def __init__(self, *, per_ip: RateLimiter, per_pair: RateLimiter) -> None:
        self.per_ip: Final[RateLimiter] = per_ip
        self.per_pair: Final[RateLimiter] = per_pair

    def check(self, ip: str, email: str) -> None:
        """
        Record a login attempt or reject it.

        Raises:
            RateLimited: If the IP or the IP + email pair is over its limit.
        """
        self.per_ip.check(ip)
        try:
            self.per_pair.check(self._pair_key(ip, email))
        except RateLimited:
            self.per_ip.forgive(ip)
            raise

    def succeeded(self, ip: str, email: str) -> None:
        """Forgive the attempt recorded by ``check``: the login did not fail."""
        self.per_ip.forgive(ip)
        self.per_pair.forgive(self._pair_key(ip, email))

    @staticmethod
    def _pair_key(ip: str, email: str) -> str:
        return f"{ip}|{_email_key(email)}"