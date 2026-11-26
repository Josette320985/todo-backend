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
import jwt

from app.core.config import Settings
from conftest import TestUser

TASKS = "/api/v1/tasks/"
WRONG_KEY = "another-secret-key-that-is-long-enough-1234567890"

# A token maker receives the app's SECRET_KEY and returns a token.
TokenMaker = Callable[[str], str]


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


def _sign(claims: dict[str, object], key: str, alg: str = "HS256") -> str:
    return jwt.encode(claims, key, algorithm=alg)


def _b64(data: dict[str, object]) -> str:
    raw = json.dumps(data, default=str).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unix_claims(exp_in_seconds: int) -> dict[str, object]:
    claims = _claims()
    claims["exp"] = int(datetime.now(timezone.utc).timestamp()) + exp_in_seconds
    claims.pop("iat")
    return claims


def _alg_none(key: str) -> str:
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(_unix_claims(300))}."


def _tampered(key: str) -> str:
    # Same valid claims with a longer expiry: only the signature is wrong.
    header, _, signature = _sign(_claims(), key).split(".")
    return f"{header}.{_b64(_unix_claims(3600))}.{signature}"


def _past() -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=1)


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


INVALID_TOKENS: dict[str, TokenMaker] = {
    "alg-none": _alg_none,
    "alg-hs512": lambda key: _sign(_claims(), key, alg="HS512"),
    "wrong-key": lambda key: _sign(_claims(), WRONG_KEY),
    "no-exp": lambda key: _sign(_claims(exp=None), key),
    "expired": lambda key: _sign(_claims(exp=_past()), key),
    "no-sub": lambda key: _sign(_claims(sub=None), key),
    "non-numeric-sub": lambda key: _sign(_claims(sub="abc"), key),
    "unknown-user": lambda key: _sign(_claims(sub="00000000-0000-0000-0000-000000000999"), key),
    "nbf-in-future": lambda key: _sign(_claims(nbf=_future()), key),
    "tampered-payload": _tampered,
    "not-a-jwt": lambda key: "not.a.jwt",
}


async def test_valid_token_is_accepted(
    client: httpx.AsyncClient, user: TestUser, settings: Settings
) -> None:
    headers = {"Authorization": f"Bearer {_sign(_claims(sub=str(user.id)), settings.SECRET_KEY)}"}
    response = await client.get(TASKS, headers=headers)
    assert response.status_code == 200


@pytest.mark.parametrize("make_token", INVALID_TOKENS.values(), ids=INVALID_TOKENS)
async def test_invalid_token_is_401(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    settings: Settings,
    make_token: TokenMaker,
) -> None:
    headers = {"Authorization": f"Bearer {make_token(settings.SECRET_KEY)}"}

    response = await client.get(TASKS, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
