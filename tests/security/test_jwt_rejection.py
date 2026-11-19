"""
TEST-03: invalid JWTs are rejected (report section 4, "JWT").

Each token below is invalid for exactly one reason; every other claim
is valid for the registered user (id 1, token_version 0). A control
test proves that a fully valid token is accepted, so the 401s are not
caused by the test setup.
"""

import base64
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from jose import jwt

from app.core.config import settings

TASKS = "/api/v1/tasks/"
WRONG_KEY = "another-secret-key-that-is-long-enough-1234567890"


def _claims(**overrides: object) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    claims: dict[str, object] = {
        "sub": "1",
        "ver": 0,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not None}


def _sign(claims: dict[str, object], key: str = "", alg: str = "HS256") -> str:
    return jwt.encode(claims, key or settings.SECRET_KEY, algorithm=alg)


def _b64(data: dict[str, object]) -> str:
    raw = json.dumps(data, default=str).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _alg_none() -> str:
    claims = _claims()
    claims["exp"] = int(datetime.now(timezone.utc).timestamp()) + 300
    claims.pop("iat")
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}."


def _tampered() -> str:
    # Same valid claims with a longer expiry: only the signature is wrong.
    header, _, signature = _sign(_claims()).split(".")
    claims = _claims()
    claims["exp"] = int(datetime.now(timezone.utc).timestamp()) + 3600
    claims.pop("iat")
    return f"{header}.{_b64(claims)}.{signature}"


def _past() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=1)


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


INVALID_TOKENS: dict[str, Callable[[], str]] = {
    "alg-none": _alg_none,
    "alg-hs512": lambda: _sign(_claims(), alg="HS512"),
    "wrong-key": lambda: _sign(_claims(), key=WRONG_KEY),
    "no-exp": lambda: _sign(_claims(exp=None)),
    "expired": lambda: _sign(_claims(exp=_past())),
    "no-sub": lambda: _sign(_claims(sub=None)),
    "non-numeric-sub": lambda: _sign(_claims(sub="abc")),
    "unknown-user": lambda: _sign(_claims(sub="999")),
    "nbf-in-future": lambda: _sign(_claims(nbf=_future())),
    "tampered-payload": _tampered,
    "not-a-jwt": lambda: "not.a.jwt",
}


async def test_valid_token_is_accepted(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    headers = {"Authorization": f"Bearer {_sign(_claims())}"}
    response = await client.get(TASKS, headers=headers)
    assert response.status_code == 200


@pytest.mark.parametrize("make_token", INVALID_TOKENS.values(), ids=INVALID_TOKENS)
async def test_invalid_token_is_401(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    make_token: Callable[[], str],
) -> None:
    headers = {"Authorization": f"Bearer {make_token()}"}

    response = await client.get(TASKS, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
