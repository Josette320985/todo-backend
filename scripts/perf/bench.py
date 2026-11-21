"""
In-process backend benchmark (PERF-07, from the measurements of sections 2 and 3).

Runs the real app (create_app) through httpx.ASGITransport on a throwaway
SQLite database and prints Markdown, ready to paste in a PR:

  1. SQL queries per endpoint (GET, POST, PUT, DELETE /tasks).
  2. GET /tasks: size, gzip size, query plan and latency for a user with
     many tasks in a large table.
  3. Event loop: /api/health latency alone and while 5 logins run (bcrypt).
  4. SQLite PRAGMAs in effect.

Usage, from todo-backend/ with the dev dependencies installed:
  python scripts/perf/bench.py [--users 50] [--tasks-per-user 2000] [--target-tasks 1000]

In-process numbers exclude the network and uvicorn: compare them only with
another run of this same script (before/after), not with ab.sh.
"""

import argparse
import asyncio
import gzip
import sqlite3
import statistics
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from common import PASSWORD, email, make_settings, migrate, seed

import httpx
from sqlalchemy import event, text

from app.main import create_app


async def timeit(fn: Callable[[], Awaitable[Any]], n: int = 30) -> tuple[float, float]:
    """Median and max latency in ms of `n` sequential calls."""
    samples: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        await fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), max(samples)


def query_plan(db: Path, sql: str) -> list[str]:
    con = sqlite3.connect(db)
    try:
        return [row[3] for row in con.execute("EXPLAIN QUERY PLAN " + sql)]
    finally:
        con.close()


async def run(
    users: int, tasks_per_user: int, target_tasks: int, samples: int = 30, bcrypt_rounds: int = 12
) -> None:
    with tempfile.TemporaryDirectory(prefix="perf-bench-") as tmp:
        db = Path(tmp) / "bench.db"
        settings = make_settings(db, bcrypt_rounds=bcrypt_rounds)
        await migrate(settings)
        total = seed(db, settings, users, tasks_per_user, first_user_tasks=target_tasks)
        print(f"# Datos: {users} usuarios, {total} tareas (usuario 1 tiene {target_tasks})\n")

        app = create_app(settings)
        queries: list[str] = []

        @event.listens_for(app.state.engine.sync_engine, "before_cursor_execute")
        def _count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
            queries.append(" ".join(statement.split())[:100])

        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://bench") as c,
        ):
            start = time.perf_counter()
            r = await c.post("/api/v1/auth/login", data={"username": email(1), "password": PASSWORD})
            r.raise_for_status()
            print(f"login: HTTP {r.status_code} en {(time.perf_counter() - start) * 1000:.0f} ms")
            headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

            print("\n## Consultas SQL por endpoint\n")

            async def count(label: str, request: Awaitable[httpx.Response]) -> httpx.Response:
                queries.clear()
                response = await request
                print(f"- {label}: HTTP {response.status_code}, **{len(queries)} consultas**")
                for q in queries:
                    print(f"    - `{q}`")
                return response

            await count("GET /tasks", c.get("/api/v1/tasks/", headers=headers))
            created = await count("POST /tasks", c.post("/api/v1/tasks/", headers=headers, json={"title": "nueva"}))
            task_id = created.json()["id"]
            await count("PUT /tasks/{id} (toggle)", c.put(f"/api/v1/tasks/{task_id}", headers=headers, json={"completed": True}))
            await count("DELETE /tasks/{id}", c.delete(f"/api/v1/tasks/{task_id}", headers=headers))

            print(f"\n## GET /tasks (usuario con {target_tasks} tareas, tabla de {total} filas)\n")
            r = await c.get("/api/v1/tasks/", headers=headers)
            raw = r.content
            print(f"- tamaño: {len(raw) / 1024:.0f} KB sin comprimir, {len(gzip.compress(raw)) / 1024:.0f} KB con gzip")
            print(f"- tareas devueltas: {len(r.json())}")
            print(f"- plan: {query_plan(db, 'SELECT * FROM tasks WHERE owner_id = 1')}")
            med, mx = await timeit(lambda: c.get("/api/v1/tasks/", headers=headers), samples)
            print(f"- latencia: mediana {med:.1f} ms, máx {mx:.1f} ms")
            first_id = r.json()[0]["id"]
            med_put, _ = await timeit(
                lambda: c.put(f"/api/v1/tasks/{first_id}", headers=headers, json={"completed": True}), samples
            )
            print(f"- PUT toggle: mediana {med_put:.1f} ms")

            print("\n## Event loop durante logins (bcrypt)\n")

            async def health_latency() -> float:
                start = time.perf_counter()
                await c.get("/api/health")
                return (time.perf_counter() - start) * 1000

            alone = statistics.median([await health_latency() for _ in range(20)])

            async def login_once() -> httpx.Response:
                return await c.post("/api/v1/auth/login", data={"username": email(2), "password": PASSWORD})

            async def health_during() -> float:
                await asyncio.sleep(0.005)
                return await health_latency()

            results = await asyncio.gather(
                *[login_once() for _ in range(5)], *[health_during() for _ in range(10)]
            )
            during = [x for x in results if isinstance(x, float)]
            print(f"- /api/health solo: {alone:.1f} ms")
            print(f"- /api/health con 5 logins: mediana {statistics.median(during):.0f} ms, máx {max(during):.0f} ms")

            async with app.state.engine.connect() as conn:
                pragmas = {
                    name: (await conn.execute(text(f"PRAGMA {name}"))).scalar()
                    for name in ("journal_mode", "foreign_keys", "busy_timeout", "synchronous")
                }
            print("\n## SQLite\n")
            print("- " + ", ".join(f"{k}={v}" for k, v in pragmas.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--tasks-per-user", type=int, default=2000)
    parser.add_argument("--target-tasks", type=int, default=1000, help="tasks of user 1, the one measured")
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(run(args.users, args.tasks_per_user, args.target_tasks, args.samples))


if __name__ == "__main__":
    main()
