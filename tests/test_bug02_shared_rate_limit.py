"""
BUG-02: the rate limit is shared by every uvicorn worker.

Each worker builds its own limiters; what they share is the SQLite file from
rate_limit_path(). Two RateLimiter objects on the same file stand in for two
workers here (separate connections, like separate processes). The live check
with a real `uvicorn --workers 4` is tests/test_perf03_workers.py (Linux,
marked slow).
"""

import multiprocessing
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.errors import RateLimited
from app.core.rate_limit import RateLimiter, rate_limit_path
from app.main import create_app
from conftest import database_path, login

NOW = 1_000_000.0


def worker(path: Path, name: str = "login", max_attempts: int = 3) -> RateLimiter:
    return RateLimiter(
        max_attempts=max_attempts, path=str(path), name=name, clock=lambda: NOW
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite+aiosqlite:///./data/todo.db", "data/todo.rate_limit.db"),
        ("sqlite+aiosqlite:////app/data/todo.db", "/app/data/todo.rate_limit.db"),
        ("sqlite+aiosqlite://", ":memory:"),
        ("sqlite+aiosqlite:///:memory:", ":memory:"),
        ("postgresql+asyncpg://u:p@db/todo", ":memory:"),
    ],
)
def test_rate_limit_path_is_next_to_the_database(url: str, expected: str) -> None:
    assert Path(rate_limit_path(url)) == Path(expected)


def test_workers_on_the_same_file_share_the_limit(tmp_path: Path) -> None:
    path = tmp_path / "limits.db"
    a, b, c = worker(path), worker(path), worker(path)

    a.check("1.2.3.4")
    b.check("1.2.3.4")
    c.check("1.2.3.4")

    for limiter in (a, b, c):
        with pytest.raises(RateLimited) as blocked:
            limiter.check("1.2.3.4")
        assert blocked.value.retry_after == 60


def test_forgive_in_one_worker_frees_the_attempt_for_all(tmp_path: Path) -> None:
    path = tmp_path / "limits.db"
    a, b = worker(path, max_attempts=1), worker(path, max_attempts=1)

    a.check("k")
    with pytest.raises(RateLimited):
        b.check("k")
    a.forgive("k")

    b.check("k")


def test_limiters_with_different_names_do_not_mix(tmp_path: Path) -> None:
    path = tmp_path / "limits.db"
    login_limiter = worker(path, name="login", max_attempts=1)
    register_limiter = worker(path, name="register", max_attempts=1)

    login_limiter.check("1.2.3.4")

    register_limiter.check("1.2.3.4")
    assert len(login_limiter) == 1 and len(register_limiter) == 1


def test_counters_survive_a_restart(tmp_path: Path) -> None:
    """A worker restarted by uvicorn reads the attempts of the old one."""
    path = tmp_path / "limits.db"
    before = worker(path, max_attempts=1)
    before.check("k")
    before.close()

    with pytest.raises(RateLimited):
        worker(path, max_attempts=1).check("k")


def _attempt(path: str, results: "multiprocessing.Queue[str]") -> None:
    limiter = RateLimiter(max_attempts=5, path=path, name="login")
    try:
        limiter.check("1.2.3.4")
        results.put("ok")
    except RateLimited:
        results.put("blocked")


def test_concurrent_processes_never_exceed_the_limit(tmp_path: Path) -> None:
    """Real processes at once: BEGIN IMMEDIATE makes count + insert atomic."""
    path = str(tmp_path / "limits.db")
    RateLimiter(max_attempts=5, path=path, name="login").close()  # create the file
    ctx = multiprocessing.get_context("spawn")
    results: "multiprocessing.Queue[str]" = ctx.Queue()
    processes = [ctx.Process(target=_attempt, args=(path, results)) for _ in range(12)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)

    outcomes = [results.get(timeout=5) for _ in processes]
    assert outcomes.count("ok") == 5, outcomes
    assert outcomes.count("blocked") == 7, outcomes


async def test_two_apps_on_one_database_share_the_login_limit(
    settings: Settings, client: httpx.AsyncClient, app: FastAPI
) -> None:
    """Two create_app() on the same database = two workers of one deployment."""
    other_worker = create_app(settings)
    transport = httpx.ASGITransport(app=other_worker)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        statuses = []
        for i in range(12):
            target = client if i % 2 else other
            response = await target.post(
                "/api/v1/auth/login",
                data={"username": f"nobody{i}@example.com", "password": "wrongpass1"},
            )
            statuses.append(response.status_code)
    other_worker.state.login_limiter.close()

    # 10 failed logins per IP, counted once across both apps.
    assert statuses == [401] * 10 + [429] * 2, statuses
    assert Path(rate_limit_path(settings.DATABASE_URL)).parent == database_path(
        settings
    ).parent


async def test_apps_with_different_databases_do_not_share(
    client: httpx.AsyncClient, tmp_path: Path, settings: Settings
) -> None:
    """Tests (and separate deployments) never inherit each other's counters."""
    for i in range(10):
        await login(client, f"nobody{i}@example.com", "wrongpass1")
    assert (await login(client, "nobody@example.com", "wrongpass1")).status_code == 429

    other_settings = settings.model_copy(
        update={"DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'other.db'}"}
    )
    other_app = create_app(other_settings)
    async with other_app.router.lifespan_context(other_app):
        transport = httpx.ASGITransport(app=other_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
            assert (await login(other, "nobody@example.com", "wrongpass1")).status_code == 401
