"""
ARQ-05: the rate limiter is a module of its own (app/core/rate_limit.py).

The unit tests drive RateLimiter with a fake clock, so the window is crossed
without sleeping. The API tests check that every app owns its limiters.
TEST-04 builds on the same FakeClock.
"""

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.errors import RateLimited
from app.core.rate_limit import LoginRateLimiter, RateLimiter
from app.main import create_app
from conftest import TEST_EMAIL, TEST_PASSWORD, TestUser, login


class FakeClock:
    """A clock that only moves when the test says so."""

    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_limiter(clock: FakeClock, **options: float) -> RateLimiter:
    settings: dict[str, float] = {"max_attempts": 3, "window_seconds": 60.0}
    settings.update(options)
    return RateLimiter(  # type: ignore[arg-type]
        clock=clock, **settings
    )


def make_login_limiter(clock: FakeClock, max_attempts: int) -> LoginRateLimiter:
    """The SEG-02 login limiter, with the same limit per IP and per IP + email."""
    return LoginRateLimiter(
        per_ip=make_limiter(clock, max_attempts=max_attempts),
        per_pair=make_limiter(clock, max_attempts=max_attempts),
    )


def test_allows_up_to_max_attempts_then_raises(clock: FakeClock) -> None:
    limiter = make_limiter(clock)

    for _ in range(3):
        limiter.check("1.2.3.4")

    with pytest.raises(RateLimited):
        limiter.check("1.2.3.4")


def test_keys_are_independent(clock: FakeClock) -> None:
    limiter = make_limiter(clock, max_attempts=1)
    limiter.check("a")

    limiter.check("b")  # another key is not affected

    with pytest.raises(RateLimited):
        limiter.check("a")


def test_retry_after_counts_down_to_the_oldest_attempt(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    limiter.check("k")  # t = 0
    clock.advance(10)
    limiter.check("k")  # t = 10
    limiter.check("k")  # t = 10

    with pytest.raises(RateLimited) as blocked:
        limiter.check("k")
    assert blocked.value.retry_after == 50  # the t = 0 attempt leaves at 60

    clock.advance(20)
    with pytest.raises(RateLimited) as later:
        limiter.check("k")
    assert later.value.retry_after == 30


def test_retry_after_rounds_up_and_is_at_least_one(clock: FakeClock) -> None:
    limiter = make_limiter(clock, max_attempts=1)
    limiter.check("k")

    clock.advance(59.2)
    with pytest.raises(RateLimited) as almost:
        limiter.check("k")
    assert almost.value.retry_after == 1


def test_window_slides_without_sleeping(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    for _ in range(3):
        limiter.check("k")
    with pytest.raises(RateLimited):
        limiter.check("k")

    clock.advance(60)  # the three attempts leave the window exactly now

    limiter.check("k")


def test_rejected_attempts_are_not_recorded(clock: FakeClock) -> None:
    limiter = make_limiter(clock, max_attempts=1)
    limiter.check("k")
    for _ in range(5):
        clock.advance(10)
        with pytest.raises(RateLimited):
            limiter.check("k")

    clock.advance(10)  # 60 s after the only recorded attempt

    limiter.check("k")


def test_expired_buckets_are_deleted(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    for key in ("a", "b", "c"):
        limiter.check(key)
    assert len(limiter) == 3

    clock.advance(61)
    limiter.check("d")  # any call frees the keys that never came back

    assert len(limiter) == 1


def test_a_partially_expired_bucket_is_kept(clock: FakeClock) -> None:
    limiter = make_limiter(clock)
    limiter.check("a")
    clock.advance(40)
    limiter.check("a")

    clock.advance(30)  # the first attempt expired, the second did not
    limiter.check("b")

    assert len(limiter) == 2


def test_max_keys_evicts_the_least_recently_used(clock: FakeClock) -> None:
    limiter = make_limiter(clock, max_attempts=1, max_keys=2)
    limiter.check("a")
    limiter.check("b")

    limiter.check("c")  # full: "a" is dropped

    assert len(limiter) == 2
    limiter.check("a")  # "a" starts from scratch
    with pytest.raises(RateLimited):
        limiter.check("c")


def test_max_keys_is_never_exceeded(clock: FakeClock) -> None:
    limiter = make_limiter(clock, max_keys=5)

    for i in range(100):
        limiter.check(f"key-{i}")
        assert len(limiter) <= 5


def test_an_existing_key_does_not_evict_others_when_full(
    clock: FakeClock,
) -> None:
    limiter = make_limiter(clock, max_attempts=3, max_keys=2)
    limiter.check("a")
    limiter.check("b")

    limiter.check("a")

    assert len(limiter) == 2


@pytest.mark.parametrize(
    "options",
    [{"max_attempts": 0}, {"window_seconds": 0}, {"max_keys": 0}],
    ids=["attempts", "window", "keys"],
)
def test_invalid_settings_are_rejected(options: dict[str, float]) -> None:
    settings: dict[str, float] = {"max_attempts": 1}
    settings.update(options)
    with pytest.raises(ValueError):
        RateLimiter(**settings)  # type: ignore[arg-type]


def test_rate_limited_is_a_429_domain_error() -> None:
    error = RateLimited(42)

    assert error.status_code == 429
    assert error.code == "rate_limit_exceeded"
    assert error.retry_after == 42


# --- API: one limiter per app -------------------------------------------------


async def test_login_is_limited_with_the_injected_clock(
    app: FastAPI, client: httpx.AsyncClient, clock: FakeClock
) -> None:
    app.state.login_limiter = make_login_limiter(clock, max_attempts=2)

    assert (await login(client, TEST_EMAIL, TEST_PASSWORD)).status_code == 401
    assert (await login(client, TEST_EMAIL, TEST_PASSWORD)).status_code == 401
    blocked = await login(client, TEST_EMAIL, TEST_PASSWORD)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limit_exceeded"

    clock.advance(60)

    assert (await login(client, TEST_EMAIL, TEST_PASSWORD)).status_code == 401


async def test_register_and_login_use_separate_limiters(
    app: FastAPI, client: httpx.AsyncClient, clock: FakeClock
) -> None:
    app.state.login_limiter = make_login_limiter(clock, max_attempts=1)
    await login(client)

    assert (await login(client)).status_code == 429
    registered = await client.post(
        "/api/v1/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )
    assert registered.status_code == 201


async def test_apps_do_not_share_counters(
    app: FastAPI, client: httpx.AsyncClient, settings: Settings
) -> None:
    other_app = create_app(settings)

    assert other_app.state.login_limiter is not app.state.login_limiter
    assert other_app.state.register_limiter is not app.state.register_limiter

async def test_me_and_logout_do_not_spend_login_attempts(
    app: FastAPI, client: httpx.AsyncClient, clock: FakeClock, user: TestUser
) -> None:
    """Every page load calls /me: it must not lock the user out of login."""
    app.state.login_limiter = make_login_limiter(clock, max_attempts=2)

    for _ in range(5):
        assert (await client.get("/api/v1/auth/me", headers=user.headers)).status_code == 200
    assert (
        await client.post("/api/v1/auth/logout", headers=user.headers)
    ).status_code == 204

    # The two failed logins allowed are still all there.
    assert (await login(client, TEST_EMAIL, "wrongpassword1")).status_code == 401
    assert (await login(client, TEST_EMAIL, "wrongpassword1")).status_code == 401
    assert (await login(client, TEST_EMAIL, "wrongpassword1")).status_code == 429
