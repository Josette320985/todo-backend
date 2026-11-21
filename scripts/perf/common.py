"""
Shared helpers for the performance scripts (PERF-07).

Every script works on a throwaway SQLite file in a temporary directory and
never touches data/todo.db. The schema comes from the real Alembic migrations
(the app's lifespan), and the rows are inserted directly with sqlite3, which is
orders of magnitude faster than going through the API.
"""

import secrets
import sqlite3
import sys
from pathlib import Path

# Make `app` importable when a script runs as `python scripts/perf/<name>.py`
# from todo-backend/.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import Settings  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import create_app  # noqa: E402

PASSWORD: str = "Password123"


def email(user_id: int) -> str:
    return f"u{user_id}@example.com"


def make_settings(db: Path, secret_key: str | None = None, bcrypt_rounds: int = 12) -> Settings:
    """Settings for a benchmark run. bcrypt keeps the production cost by default."""
    return Settings(
        _env_file=None,
        SECRET_KEY=secret_key or secrets.token_urlsafe(48),
        DATABASE_URL=f"sqlite+aiosqlite:///{db.as_posix()}",
        ENVIRONMENT="production",
        LOG_LEVEL="WARNING",
        BCRYPT_ROUNDS=bcrypt_rounds,
    )


async def migrate(settings: Settings) -> None:
    """Create the schema by running the app lifespan (Alembic migrations)."""
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        if not app.state.migrated:
            raise RuntimeError(f"Could not migrate {settings.DATABASE_URL}")


def seed(
    db: Path,
    settings: Settings,
    users: int,
    tasks_per_user: int,
    first_user_tasks: int | None = None,
) -> int:
    """
    Insert `users` users (u1@example.com ... with PASSWORD) and their tasks.

    User 1 gets `first_user_tasks` tasks when given, so one user can have a
    realistic list while the table is large. Returns the number of tasks.
    """
    hashed: str = hash_password(PASSWORD, settings.BCRYPT_ROUNDS)
    rows: list[tuple[str, bool, int]] = []
    for user_id in range(1, users + 1):
        count = first_user_tasks if (user_id == 1 and first_user_tasks is not None) else tasks_per_user
        rows += [(f"Tarea {user_id}-{k}", k % 3 == 0, user_id) for k in range(count)]
    con = sqlite3.connect(db)
    try:
        con.executemany(
            "INSERT INTO users (id, email, hashed_password, token_version) VALUES (?, ?, ?, 0)",
            [(i, email(i), hashed) for i in range(1, users + 1)],
        )
        con.executemany(
            "INSERT INTO tasks (title, completed, owner_id) VALUES (?, ?, ?)", rows
        )
        con.commit()
    finally:
        con.close()
    return len(rows)


def token(user_id: int, settings: Settings) -> str:
    """A valid access token for a seeded user (token_version 0)."""
    return create_access_token(str(user_id), 0, settings)
