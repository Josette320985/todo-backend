"""
Repositories (ARQ-02).

The API behaviour is already pinned by the characterization tests
(TEST-02, tests/api/); these tests check the repositories directly,
especially that every read and delete is scoped by owner.
"""

import re
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from tests.conftest import TestUser

API_DIR: Path = Path(__file__).resolve().parents[1] / "app" / "api"


@pytest.fixture
async def session(
    app: FastAPI, client: httpx.AsyncClient
) -> AsyncIterator[AsyncSession]:
    """A session on the test app's database (tables created by `client`)."""
    async with app.state.session_factory() as s:
        yield s


async def test_list_by_owner_only_returns_own_tasks(
    session: AsyncSession, user: TestUser, other_user: TestUser
) -> None:
    repo = TaskRepository(session)
    await repo.add(Task(title="mine", owner_id=user.id))
    await repo.add(Task(title="theirs", owner_id=other_user.id))

    titles = [t.title for t in await repo.list_by_owner(user.id)]

    assert titles == ["mine"]


async def test_list_by_owner_limit_and_offset(
    session: AsyncSession, user: TestUser
) -> None:
    repo = TaskRepository(session)
    for i in range(5):
        await repo.add(Task(title=f"t{i}", owner_id=user.id))

    assert len(await repo.list_by_owner(user.id)) == 5
    assert len(await repo.list_by_owner(user.id, limit=2)) == 2
    assert len(await repo.list_by_owner(user.id, limit=10, offset=3)) == 2


async def test_get_owned_hides_other_users_tasks(
    session: AsyncSession, user: TestUser, other_user: TestUser
) -> None:
    repo = TaskRepository(session)
    task = await repo.add(Task(title="mine", owner_id=user.id))

    assert await repo.get_owned(task.id, user.id) is task
    assert await repo.get_owned(task.id, other_user.id) is None
    assert await repo.get_owned(999_999, user.id) is None


async def test_delete_owned(
    session: AsyncSession, user: TestUser, other_user: TestUser
) -> None:
    repo = TaskRepository(session)
    task = await repo.add(Task(title="mine", owner_id=user.id))

    assert await repo.delete_owned(task.id, other_user.id) is False
    assert await repo.get_owned(task.id, user.id) is not None

    assert await repo.delete_owned(task.id, user.id) is True
    assert await repo.get_owned(task.id, user.id) is None
    assert await repo.delete_owned(task.id, user.id) is False


async def test_user_repository(session: AsyncSession, user: TestUser) -> None:
    repo = UserRepository(session)

    by_email = await repo.get_by_email(user.email)
    assert by_email is not None and by_email.id == user.id
    assert await repo.get_by_id(user.id) is by_email
    assert await repo.get_by_email("nobody@example.com") is None
    assert await repo.get_by_id(999_999) is None

    new = await repo.add(User(email="new@example.com", hashed_password="x"))
    assert new.id is not None
    assert new.token_version == 0


def test_no_queries_in_api_layer() -> None:
    """Acceptance criterion of ARQ-02: queries only live in app/repositories."""
    pattern = re.compile(r"select\(|db\.execute|db\.delete")
    offenders = [
        f"{path.relative_to(API_DIR)}:{n}"
        for path in API_DIR.rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []
