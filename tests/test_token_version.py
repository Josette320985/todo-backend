from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI
from jose import jwt
from sqlalchemy import inspect, text

from app.core.config import Settings
from app.db.migrations import run_migrations


def _token(claims: dict[str, object], settings: Settings) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode({**claims, "exp": exp}, settings.SECRET_KEY, "HS256")


async def test_token_without_version_is_401(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    headers = {"Authorization": f"Bearer {_token({'sub': '1'}, settings)}"}
    response = await client.get("/api/v1/tasks/", headers=headers)
    assert response.status_code == 401


async def test_token_with_wrong_version_is_401(
    client: httpx.AsyncClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    token = _token({"sub": "1", "ver": 1}, settings)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/api/v1/tasks/", headers=headers)
    assert response.status_code == 401


async def test_migration_adds_column_to_old_db(app: FastAPI) -> None:
    # Empty database (lifespan not run): create the pre-SEG-H10 schema.
    # Since ARQ-03 the column is added by migration 0002, not by a patch.
    async with app.state.engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255),"
            " hashed_password VARCHAR(255))"
        ))
        await conn.execute(text(
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, title VARCHAR(200),"
            " owner_id INTEGER REFERENCES users (id))"
        ))
        await conn.run_sync(run_migrations)
        await conn.run_sync(run_migrations)  # idempotent
        columns = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("users")}
        )
    await app.state.engine.dispose()
    assert "token_version" in columns
