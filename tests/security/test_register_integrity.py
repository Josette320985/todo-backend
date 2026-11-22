"""SEG-H05: a registration race (IntegrityError) answers 400, not 500."""

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.repositories.user_repository import UserRepository
from conftest import TEST_EMAIL, TEST_PASSWORD
from helpers import register


async def test_integrity_error_on_register_is_400(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate the loser of a concurrent registration race."""

    async def raise_integrity_error(
        self: UserRepository, user: object
    ) -> None:
        raise IntegrityError(
            "INSERT INTO users ...",
            {},
            Exception("UNIQUE constraint failed: users.email"),
        )

    monkeypatch.setattr(UserRepository, "add", raise_integrity_error)

    response = await register(client, TEST_EMAIL, TEST_PASSWORD)

    assert response.status_code == 400
    assert response.json()["code"] == "email_already_registered"
