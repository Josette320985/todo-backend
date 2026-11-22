"""
cProfile of GET /api/v1/tasks/ in process (PERF-07, section 3 "Perfil").

Seeds a throwaway database (20 users x 20 tasks, like ab.sh), makes 50
warm-up requests and profiles the next N, then prints the time per request
and the share of each library, plus the top functions of the project itself.

Usage, from todo-backend/:
  python scripts/perf/prof.py [--requests 1000] [--top 15]

The share of "httpx (cliente de prueba)" is the in-process client, not the API.
"""

import argparse
import asyncio
import cProfile
import pstats
import tempfile
from pathlib import Path

from common import REPO_ROOT, make_settings, migrate, seed, token

import httpx

from app.main import create_app

GROUPS: dict[str, tuple[str, ...]] = {
    "aiosqlite (hilo + cola)": ("aiosqlite",),
    "sqlalchemy": ("sqlalchemy",),
    "jose (JWT)": ("jose",),
    "pydantic": ("pydantic",),
    "fastapi/starlette": ("fastapi", "starlette"),
    "httpx (cliente de prueba)": ("httpx",),
    "código del proyecto (app/)": (str(REPO_ROOT / "app"),),
}


async def profile(requests: int) -> pstats.Stats:
    with tempfile.TemporaryDirectory(prefix="perf-prof-") as tmp:
        db = Path(tmp) / "prof.db"
        settings = make_settings(db, bcrypt_rounds=4)
        await migrate(settings)
        seed(db, settings, users=20, tasks_per_user=20)
        app = create_app(settings)
        headers = {"Authorization": f"Bearer {token(1, settings)}"}
        transport = httpx.ASGITransport(app=app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://prof") as c,
        ):
            for _ in range(50):
                (await c.get("/api/v1/tasks/", headers=headers)).raise_for_status()
            profiler = cProfile.Profile()
            profiler.enable()
            for _ in range(requests):
                await c.get("/api/v1/tasks/", headers=headers)
            profiler.disable()
    return pstats.Stats(profiler)


def report(stats: pstats.Stats, requests: int, top: int) -> None:
    total: float = stats.total_tt  # type: ignore[attr-defined]
    shares: dict[str, float] = dict.fromkeys(GROUPS, 0.0)
    other = 0.0
    raw: dict[tuple[str, int, str], tuple[int, int, float, float, object]] = stats.stats  # type: ignore[attr-defined]
    for (filename, _, _), (_, _, tottime, _, _) in raw.items():
        for name, patterns in GROUPS.items():
            if any(p in filename for p in patterns):
                shares[name] += tottime
                break
        else:
            other += tottime

    print(f"## Perfil de GET /tasks ({requests} requests)\n")
    print(f"- tiempo por request: **{total / requests * 1000:.2f} ms**\n")
    print("| % | Grupo |\n| ---: | --- |")
    for name, value in sorted(shares.items(), key=lambda kv: -kv[1]):
        print(f"| {value / total * 100:.1f} | {name} |")
    print(f"| {other / total * 100:.1f} | resto (asyncio, stdlib) |")

    print(f"\n### Funciones de app/ con más tiempo propio (top {top})\n")
    own = [
        (tottime, f"{Path(f).relative_to(REPO_ROOT)}:{line} {fn}")
        for (f, line, fn), (_, _, tottime, _, _) in raw.items()
        if f.startswith(str(REPO_ROOT / "app"))
    ]
    for tottime, where in sorted(own, reverse=True)[:top]:
        print(f"- {tottime / requests * 1000:.3f} ms/request · `{where}`")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()
    report(asyncio.run(profile(args.requests)), args.requests, args.top)


if __name__ == "__main__":
    main()
