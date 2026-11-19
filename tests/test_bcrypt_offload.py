"""Tests for SEG-H03 / PERF-01: bcrypt must not block the event loop.

bcrypt is CPU-bound (~0.25 s at the production cost). If it runs in the event
loop, every other request waits for it. These tests replace the hash function
with one that blocks for 0.3 s and check that /api/health is served *while it
is still blocked*.
"""

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import auth as auth_module
from conftest import login

# The patched hash blocks 6x longer than health is allowed to take.
BLOCKING_SECONDS = 0.3
MAX_HEALTH_SECONDS = 0.05


def _blocking_verify(plain: str, hashed: str, finished: threading.Event) -> bool:
    time.sleep(BLOCKING_SECONDS)
    finished.set()
    return True


def _blocking_hash(password: str, rounds: int, finished: threading.Event) -> str:
    time.sleep(BLOCKING_SECONDS)
    finished.set()
    return "$2b$04$" + "x" * 53


async def _assert_health_wins_during(
    client: httpx.AsyncClient,
    slow_request: Callable[[], Awaitable[httpx.Response]],
    finished: threading.Event,
    wait_for_hash_start: float = 0.05,
) -> None:
    """
    Fail unless /api/health is answered while the slow hash is still running.

    `finished` is set by the blocking function the moment it returns, so the
    assertion does not depend on timers: if the loop was blocked, health can
    only be served after the hash is over.
    """
    slow: asyncio.Task[httpx.Response] = asyncio.create_task(slow_request())
    await asyncio.sleep(wait_for_hash_start)  # let the request reach the hash

    try:
        response = await asyncio.wait_for(
            client.get("/api/health"), timeout=MAX_HEALTH_SECONDS
        )
    except TimeoutError:
        pytest.fail("/api/health no se sirvió: bcrypt bloqueó el event loop")

    assert response.status_code == 200
    assert not finished.is_set(), (
        "/api/health esperó a que terminara el hash: bcrypt bloqueó el event loop"
    )
    assert not slow.done()
    assert (await slow).status_code in (200, 201, 401)


async def test_health_answers_while_a_login_hash_runs(
    app: FastAPI,
    client: httpx.AsyncClient,
    user: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finished = threading.Event()
    monkeypatch.setattr(
        auth_module, "verify_password", lambda p, h: _blocking_verify(p, h, finished)
    )
    await _assert_health_wins_during(
        client,
        lambda: client.post(
            "/api/v1/auth/login",
            data={"username": "user@example.com", "password": "password123"},
        ),
        finished,
    )


async def test_health_answers_while_a_registration_hash_runs(
    app: FastAPI,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finished = threading.Event()
    monkeypatch.setattr(
        auth_module, "hash_password", lambda p, r: _blocking_hash(p, r, finished)
    )
    await _assert_health_wins_during(
        client,
        lambda: client.post(
            "/api/v1/auth/register",
            json={"email": "nuevo@example.com", "password": "password123"},
        ),
        finished,
    )


async def test_dummy_verify_of_unknown_user_does_not_block(
    app: FastAPI,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dummy hash for unknown emails costs a full bcrypt run on first use."""
    finished = threading.Event()
    monkeypatch.setattr(
        auth_module,
        "dummy_password_hash",
        lambda rounds: _blocking_hash("", rounds, finished),
    )
    await _assert_health_wins_during(
        client,
        lambda: client.post(
            "/api/v1/auth/login",
            data={"username": "no-existe@example.com", "password": "password123"},
        ),
        finished,
    )


async def test_login_still_works(client: httpx.AsyncClient, user: object) -> None:
    """The thread offload must not change the result of a normal login."""
    response = await login(client)
    assert response.status_code == 200
    assert response.json()["access_token"]
