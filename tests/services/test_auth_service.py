import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.core.errors import EmailAlreadyRegistered, InvalidCredentials
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.auth_service import AuthService


async def test_register_hashes_password(
    app: FastAPI, client: httpx.AsyncClient, settings: Settings
) -> None:
    async with app.state.session_factory() as db:
        service = AuthService(UserRepository(db), settings)
        user = await service.register(
            UserCreate(email="Ana@Example.com", password="password123")
        )

        assert user.email == "ana@example.com"
        assert user.hashed_password != "password123"
        assert user.hashed_password.startswith("$2")


async def test_register_duplicate_email(
    app: FastAPI, client: httpx.AsyncClient, settings: Settings
) -> None:
    async with app.state.session_factory() as db:
        service = AuthService(UserRepository(db), settings)
        await service.register(
            UserCreate(email="ana@example.com", password="password123")
        )

        with pytest.raises(EmailAlreadyRegistered) as exc:
            await service.register(
                UserCreate(email="ANA@example.com", password="password123")
            )

        assert exc.value.status_code == 400


async def test_authenticate_valid_credentials(
    app: FastAPI, client: httpx.AsyncClient, settings: Settings
) -> None:
    async with app.state.session_factory() as db:
        service = AuthService(UserRepository(db), settings)
        created = await service.register(
            UserCreate(email="ana@example.com", password="password123")
        )

        user = await service.authenticate(
            "ANA@example.com", "password123", "127.0.0.1"
        )

        assert user.id == created.id


async def test_authenticate_wrong_password(
    app: FastAPI, client: httpx.AsyncClient, settings: Settings
) -> None:
    async with app.state.session_factory() as db:
        service = AuthService(UserRepository(db), settings)
        await service.register(
            UserCreate(email="ana@example.com", password="password123")
        )

        with pytest.raises(InvalidCredentials) as exc:
            await service.authenticate(
                "ana@example.com", "wrong1234", "127.0.0.1"
            )

        assert exc.value.status_code == 401
        assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


async def test_authenticate_unknown_email(
    app: FastAPI, client: httpx.AsyncClient, settings: Settings
) -> None:
    async with app.state.session_factory() as db:
        service = AuthService(UserRepository(db), settings)

        with pytest.raises(InvalidCredentials):
            await service.authenticate(
                "nadie@example.com", "password123", "127.0.0.1"
            )
