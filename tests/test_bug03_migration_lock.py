"""
BUG-03: only one process at a time runs the migrations.

With several uvicorn workers every worker migrates on startup. Before the
lock they raced ("table alembic_version already exists", "database is
locked") and some reported the database as unavailable. The live check is
the PERF-03 suite (tests/test_perf03_workers.py, Linux, marked slow); here
real processes migrate the same fresh database at once.
"""

import asyncio
import multiprocessing
import sqlite3
import time
from pathlib import Path

import httpx
import pytest

import app.db.migrations as migrations
from app.core.config import Settings
from app.db.migrations import MigrationLock
from app.db.session import create_engine, sqlite_sibling_path
from app.main import create_app, migrate

PROCESSES = 6


def url_for(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _hold_lock(url: str, held: "multiprocessing.Event", seconds: float) -> None:
    lock = MigrationLock(url)
    lock.acquire()
    held.set()
    time.sleep(seconds)
    lock.release()


def _hold_lock_forever(url: str, held: "multiprocessing.Event") -> None:
    MigrationLock(url).acquire()
    held.set()
    time.sleep(60)


def _migrate(url: str, start: "multiprocessing.Event", errors: "multiprocessing.Queue[str]") -> None:
    async def run() -> None:
        engine = create_engine(url)
        try:
            await migrate(engine)
        finally:
            await engine.dispose()

    start.wait()
    try:
        asyncio.run(run())
        errors.put("")
    except Exception as exc:  # reported to the parent, not swallowed
        errors.put(f"{type(exc).__name__}: {exc}")


def test_lock_file_is_next_to_the_database(tmp_path: Path) -> None:
    lock = MigrationLock(url_for(tmp_path / "todo.db"))

    assert lock.path == tmp_path / "todo.migrate.lock"
    assert sqlite_sibling_path("sqlite+aiosqlite:///./data/todo.db", "migrate.lock") == Path(
        "data/todo.migrate.lock"
    )


@pytest.mark.parametrize("url", ["sqlite+aiosqlite://", "postgresql+asyncpg://u:p@db/x"])
def test_no_file_means_no_lock(url: str) -> None:
    lock = MigrationLock(url)

    lock.acquire()  # nothing to share between processes: a no-op
    lock.release()
    assert lock.path is None


def test_a_second_process_waits_for_the_first(tmp_path: Path) -> None:
    url = url_for(tmp_path / "todo.db")
    ctx = multiprocessing.get_context("spawn")
    held = ctx.Event()
    holder = ctx.Process(target=_hold_lock, args=(url, held, 1.0))
    holder.start()
    assert held.wait(timeout=30)

    started = time.monotonic()
    lock = MigrationLock(url)
    lock.acquire()
    waited = time.monotonic() - started
    lock.release()
    holder.join(timeout=30)

    assert waited >= 0.5, f"took the lock after {waited:.2f} s while another process held it"


def test_waiting_too_long_fails_like_a_locked_database(tmp_path: Path) -> None:
    url = url_for(tmp_path / "todo.db")
    holder = MigrationLock(url)
    holder.acquire()
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            MigrationLock(url, timeout=0.1).acquire()
    finally:
        holder.release()


def test_the_lock_is_freed_if_its_process_dies(tmp_path: Path) -> None:
    url = url_for(tmp_path / "todo.db")
    ctx = multiprocessing.get_context("spawn")
    held = ctx.Event()
    holder = ctx.Process(target=_hold_lock_forever, args=(url, held))
    holder.start()
    assert held.wait(timeout=30)
    holder.kill()
    holder.join(timeout=30)

    lock = MigrationLock(url, timeout=5)
    lock.acquire()  # the OS released the dead process's lock
    lock.release()


def test_processes_migrating_at_once_do_not_race(tmp_path: Path) -> None:
    db_file = tmp_path / "todo.db"
    url = url_for(db_file)
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    errors: "multiprocessing.Queue[str]" = ctx.Queue()
    processes = [ctx.Process(target=_migrate, args=(url, start, errors)) for _ in range(PROCESSES)]
    for process in processes:
        process.start()
    start.set()  # all of them migrate the same fresh database at once
    for process in processes:
        process.join(timeout=60)

    results = [errors.get(timeout=10) for _ in processes]
    assert results == [""] * PROCESSES, [r for r in results if r]
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [
            ("0003",)
        ]


async def test_startup_keeps_running_when_the_lock_wait_times_out(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ERR-05 still holds: /api/health is 200, /ready is 503 and retries later."""
    monkeypatch.setattr(migrations, "MIGRATION_LOCK_TIMEOUT_SECONDS", 0.1)
    holder = MigrationLock(settings.DATABASE_URL)
    holder.acquire()
    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                assert (await client.get("/api/health")).status_code == 200
                assert (await client.get("/api/health/ready")).status_code == 503

                holder.release()

                assert (await client.get("/api/health/ready")).status_code == 200
    finally:
        holder.release()
