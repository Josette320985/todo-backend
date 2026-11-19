from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt
from sqlalchemy import inspect, text

from app.core.config import get_settings
from app.main import add_token_version_column, app

engine = app.state.engine


def _token(claims: dict[str, object]) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode({**claims, "exp": exp}, get_settings().SECRET_KEY, "HS256")


async def test_token_without_version_is_401(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    headers = {"Authorization": f"Bearer {_token({'sub': '1'})}"}
    response = await client.get("/api/v1/tasks/", headers=headers)
    assert response.status_code == 401


async def test_token_with_wrong_version_is_401(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    headers = {"Authorization": f"Bearer {_token({'sub': '1', 'ver': 1})}"}
    response = await client.get("/api/v1/tasks/", headers=headers)
    assert response.status_code == 401


async def test_migration_adds_column_to_old_db() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE tasks"))
        await conn.execute(text("DROP TABLE users"))
        await conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255),"
            " hashed_password VARCHAR(255))"
        ))
        await conn.run_sync(add_token_version_column)
        await conn.run_sync(add_token_version_column)  # idempotent
        columns = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("users")}
        )
    assert "token_version" in columns
