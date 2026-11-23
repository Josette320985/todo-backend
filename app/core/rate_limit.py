"""Sliding-window rate limiter (ARQ-05), shared between workers (BUG-02).

Moved out of ``app/api/v1/auth.py`` so the limiter is a module of its own:

* ``RateLimiter.check(key)`` raises ``RateLimited(retry_after)`` instead of an
  ``HTTPException``; ERR-03 turns ``retry_after`` into the ``Retry-After``
  header and SEG-02 builds ``LoginRateLimiter`` on top of it.
* The clock is injectable, so tests move time forward without ``sleep``.
* Storage is bounded: attempts that left the window are deleted, and the
  number of tracked keys never exceeds ``max_keys``.
* There is no module-level state. ``create_app`` builds the limiters and
  keeps them in ``app.state`` (ARQ-01).

The attempts live in SQLite. With several uvicorn workers (PERF-03) every
worker opens the same file (``rate_limit_path``), so the limit is the same
whichever process answers; each ``check`` runs in a ``BEGIN IMMEDIATE``
transaction, so counting and recording an attempt is atomic across processes.
Without a file (``path=":memory:"``, the default) the counters belong to that
limiter alone: unit tests and separate apps never share them.

``check`` stays synchronous: it is a few indexed statements on a local file,
far below the cost of the bcrypt run it protects.
"""

import math
import sqlite3
import time
import weakref
from collections.abc import Callable
from typing import Final

from app.core.emails import normalize_email
from app.core.errors import RateLimited
from app.db.session import sqlite_sibling_path

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
# ``max_attempts`` rows, so storage stays bounded however many distinct
# clients (or forged keys) show up.
DEFAULT_MAX_KEYS: Final[int] = 10_000

# How long a worker waits for another one holding the write lock.
_BUSY_TIMEOUT_SECONDS: Final[float] = 5.0

# Returns the current time in seconds. Wall-clock time, not monotonic: the
# attempts are shared between processes and survive a restart, and a
# monotonic clock starts again from zero on every boot.
Clock = Callable[[], float]

_SCHEMA: Final[tuple[str, ...]] = (
    "CREATE TABLE IF NOT EXISTS rate_limit_attempts ("
    " limiter TEXT NOT NULL, key TEXT NOT NULL, at REAL NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_rate_limit_attempts_key"
    " ON rate_limit_attempts (limiter, key, at)",
    "CREATE INDEX IF NOT EXISTS ix_rate_limit_attempts_at"
    " ON rate_limit_attempts (limiter, at)",
)


def rate_limit_path(database_url: str) -> str:
    """
    File for the shared counters, next to the SQLite database of the app.

    ``data/todo.db`` gives ``data/todo.rate_limit.db``: every worker of the
    same deployment opens the same file, and every test app (its own
    database in ``tmp_path``) gets its own. Anything else (an in-memory
    database, another engine) keeps the counters in memory, per process.
    """
    path = sqlite_sibling_path(database_url, "rate_limit.db")
    return ":memory:" if path is None else str(path)


class RateLimiter:
    """
    Allow at most ``max_attempts`` calls per key in a sliding window.

    Every accepted call is recorded; a rejected call is not, so a blocked
    client is released ``window_seconds`` after its oldest recorded call.

    Args:
        max_attempts (int): Calls allowed per key inside the window.
        window_seconds (float): Length of the sliding window.
        max_keys (int): Maximum number of keys tracked at once. When it is
            reached, the least recently used key is dropped to make room.
        clock (Clock): Time source. Tests pass a fake one.
        path (str): SQLite file shared by the workers (``rate_limit_path``),
            or ``":memory:"`` for counters private to this limiter.
        name (str): Separates the limiters that share one file.
    """

    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
        max_keys: int = DEFAULT_MAX_KEYS,
        clock: Clock = time.time,
        path: str = ":memory:",
        name: str = "default",
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
        self.name: Final[str] = name
        self._clock: Final[Clock] = clock
        self._path: Final[str] = path
        # Opened on first use: an app that never limits anything (most test
        # apps) never opens the file.
        self._connection: sqlite3.Connection | None = None

    def __len__(self) -> int:
        """Number of keys currently tracked."""
        row = self._db().execute(
            "SELECT COUNT(DISTINCT key) FROM rate_limit_attempts WHERE limiter = ?",
            (self.name,),
        ).fetchone()
        return int(row[0])

    def check(self, key: str) -> None:
        """
        Record one call for ``key`` or reject it.

        Raises:
            RateLimited: If ``key`` already used its ``max_attempts`` in the
                window. ``retry_after`` is the whole seconds (at least 1)
                until the oldest recorded call leaves the window.
        """
        now: float = self._clock()
        db = self._db()
        retry_after: int | None = None
        db.execute("BEGIN IMMEDIATE")
        try:
            # A call leaves the window exactly ``window_seconds`` after it.
            db.execute(
                "DELETE FROM rate_limit_attempts WHERE limiter = ? AND at <= ?",
                (self.name, now - self.window_seconds),
            )
            count, oldest = db.execute(
                "SELECT COUNT(*), MIN(at) FROM rate_limit_attempts"
                " WHERE limiter = ? AND key = ?",
                (self.name, key),
            ).fetchone()
            if count >= self.max_attempts:
                retry_after = max(1, math.ceil(oldest + self.window_seconds - now))
            else:
                if count == 0:
                    self._make_room(db)
                db.execute(
                    "INSERT INTO rate_limit_attempts (limiter, key, at) VALUES (?, ?, ?)",
                    (self.name, key, now),
                )
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        if retry_after is not None:
            raise RateLimited(retry_after)

    def forgive(self, key: str) -> None:
        """
        Remove the most recent call recorded for ``key``, if any.

        ``check`` records the call before the work it protects runs, so
        concurrent requests cannot all slip past the limit. Callers that only
        want to count failures forgive the call once the work succeeded.
        """
        self._db().execute(
            "DELETE FROM rate_limit_attempts WHERE rowid = ("
            " SELECT rowid FROM rate_limit_attempts WHERE limiter = ? AND key = ?"
            " ORDER BY at DESC, rowid DESC LIMIT 1)",
            (self.name, key),
        )

    def close(self) -> None:
        """Close the connection; the next call opens it again."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _make_room(self, db: sqlite3.Connection) -> None:
        """Before adding a new key, drop the least recently used one if full."""
        (keys,) = db.execute(
            "SELECT COUNT(DISTINCT key) FROM rate_limit_attempts WHERE limiter = ?",
            (self.name,),
        ).fetchone()
        if keys < self.max_keys:
            return
        db.execute(
            "DELETE FROM rate_limit_attempts WHERE limiter = ? AND key = ("
            " SELECT key FROM rate_limit_attempts WHERE limiter = ?"
            " GROUP BY key ORDER BY MAX(at), MAX(rowid) LIMIT 1)",
            (self.name, self.name),
        )

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            # Autocommit mode: ``check`` opens its own BEGIN IMMEDIATE. The
            # event loop calls the limiter from a single thread, but not
            # always the thread that created it.
            connection = sqlite3.connect(
                self._path,
                timeout=_BUSY_TIMEOUT_SECONDS,
                isolation_level=None,
                check_same_thread=False,
            )
            if self._path != ":memory:":
                connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            for statement in _SCHEMA:
                connection.execute(statement)
            # Closed with the limiter even if nobody calls close() (a test,
            # an app replaced in app.state): no ResourceWarning on collection.
            weakref.finalize(self, connection.close)
            self._connection = connection
        return self._connection


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

    def close(self) -> None:
        """Close the connections of both limiters."""
        self.per_ip.close()
        self.per_pair.close()

    @staticmethod
    def _pair_key(ip: str, email: str) -> str:
        return f"{ip}|{_email_key(email)}"