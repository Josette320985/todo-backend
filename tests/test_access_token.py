"""
TEST-04: access token expiry with a fixed clock.

create_access_token reads datetime.now(); the tests replace it with a fixed
instant, so the claims are exact and the expiry boundary can be checked
without sleeping. The tokens are then sent to the real API, which decodes
them with the real clock.
"""

from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest

import app.core.security as security
from app.core.config import Settings
from app.core.security import create_access_token
from conftest import TestUser

TASKS_URL = "/api/v1/tasks/"
FIXED_NOW = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def freeze_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    """Make create_access_token see `now` as the current time."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> "FrozenDatetime":
            return cls.fromtimestamp(now.timestamp(), tz=timezone.utc)

    monkeypatch.setattr(security, "datetime", FrozenDatetime)


def test_claims_use_the_configured_lifetime(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze_clock(monkeypatch, FIXED_NOW)

    token = create_access_token("7", 3, settings)
    claims = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        options={"verify_exp": False},
    )

    lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    assert claims == {
        "sub": "7",
        "ver": 3,
        "iat": int(FIXED_NOW.timestamp()),
        "exp": int((FIXED_NOW + lifetime).timestamp()),
    }


@pytest.mark.parametrize(
    ("age_offset", "expected_status"),
    [
        # Issued `lifetime - 10 s` ago: 10 seconds of validity left.
        pytest.param(timedelta(seconds=-10), 200, id="just-before-expiry"),
        # Issued `lifetime + 10 s` ago: expired 10 seconds ago.
        pytest.param(timedelta(seconds=10), 401, id="just-after-expiry"),
    ],
)
async def test_token_expires_after_its_lifetime(
    client: httpx.AsyncClient,
    user: TestUser,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    age_offset: timedelta,
    expected_status: int,
) -> None:
    lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    issued_at = datetime.now(timezone.utc) - lifetime - age_offset
    freeze_clock(monkeypatch, issued_at)

    token = create_access_token(str(user.id), 0, settings)
    response = await client.get(
        TASKS_URL, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == expected_status, response.text
