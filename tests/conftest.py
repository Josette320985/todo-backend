"""
Shared test fixtures (TEST-01).

Every test builds its own app with create_app(settings) (ARQ-01):
a fresh SQLite database in tmp_path, a random SECRET_KEY and the minimum
bcrypt cost. No environment variables are touched and the real `.env`
and `data/todo.db` are never used.

The Alembic migrations run once per session into a template database;
`client` copies it into the test's database file before starting the app,
so each test skips ~50 ms of migrations. The app still runs the migrations
on startup (a no-op at head). Tests that build their own schema first
(tests/test_migrations.py) keep their file: the copy only happens when the
database does not exist yet.

Fixtures:
    settings      Settings of the test app.
    app           The FastAPI app (its lifespan runs inside `client`).
    client        In-process httpx.AsyncClient for the app.
    make_user     Factory: register + log in a user, returns a TestUser.
    user          Default user (TEST_EMAIL); `auth_headers` is its header.
    other_user    A second user, to test access to someone else's data.
    count_queries Records the SQL statements the app executes.
"""

import secrets
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event

from app.core.config import Settings
from app.db.migrations import run_migrations
from app.main import create_app

TEST_EMAIL: str = "user@example.com"
OTHER_EMAIL: str = "other@example.com"
TEST_PASSWORD: str = "password123"

# Lowest cost bcrypt accepts. Production keeps the default (12).
TEST_BCRYPT_ROUNDS: int = 4


@dataclass(frozen=True)
class TestUser:
    """A registered and logged-in user."""

    __test__ = False  # not a test class, despite the name

    id: uuid.UUID
    email: str
    password: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


class QueryLog(list[str]):
    """SQL statements executed by the app, in order."""

    @property
    def count(self) -> int:
        return len(self)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings for one test: temporary database, random key, fast bcrypt."""
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        SECRET_KEY=secrets.token_urlsafe(48),
        DATABASE_URL=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        ENVIRONMENT="test",
        BCRYPT_ROUNDS=TEST_BCRYPT_ROUNDS,
    )


def database_path(settings: Settings) -> Path:
    """File behind a sqlite+aiosqlite DATABASE_URL."""
    return Path(settings.DATABASE_URL.split("///", 1)[1])


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A database at the latest Alembic revision, built once per session."""
    path = tmp_path_factory.mktemp("template") / "migrated.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        with engine.begin() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()
    return path


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(
    app: FastAPI, settings: Settings, migrated_template: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """In-process HTTP client, inside the app lifespan (migrated database)."""
    database = database_path(settings)
    if not database.exists():
        shutil.copyfile(migrated_template, database)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            yield c


async def login(
    client: httpx.AsyncClient,
    email: str = TEST_EMAIL,
    password: str = TEST_PASSWORD,
) -> httpx.Response:
    """POST the login form and return the raw response."""
    return await client.post(
        "/api/v1/auth/login", data={"username": email, "password": password}
    )


MakeUser = Callable[..., Awaitable[TestUser]]


@pytest.fixture
def make_user(client: httpx.AsyncClient) -> MakeUser:
    """Return a factory that registers and logs in a user."""

    async def _make_user(
        email: str = TEST_EMAIL, password: str = TEST_PASSWORD
    ) -> TestUser:
        registered = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": password}
        )
        assert registered.status_code == 201, registered.text
        logged_in = await login(client, email, password)
        assert logged_in.status_code == 200, logged_in.text
        return TestUser(
            id=uuid.UUID(registered.json()["id"]),
            email=email,
            password=password,
            token=logged_in.json()["access_token"],
        )

    return _make_user


@pytest.fixture
async def user(make_user: MakeUser) -> TestUser:
    return await make_user(TEST_EMAIL)


@pytest.fixture
async def other_user(make_user: MakeUser, user: TestUser) -> TestUser:
    return await make_user(OTHER_EMAIL)


@pytest.fixture
def auth_headers(user: TestUser) -> dict[str, str]:
    """Authorization header of the default user."""
    return user.headers


@pytest.fixture
def count_queries(app: FastAPI) -> Iterator[QueryLog]:
    """
    Record every SQL statement the app executes (for TEST-06).

    Call `count_queries.clear()` right before the request you measure.
    """
    log = QueryLog()

    def _record(
        conn: Any, cursor: Any, statement: str, *args: Any
    ) -> None:
        log.append(statement)

    sync_engine = app.state.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _record)
    yield log
    event.remove(sync_engine, "before_cursor_execute", _record)
