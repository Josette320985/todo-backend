"""
PERF-07: the scripts in scripts/perf/ still run against the current app.

Tiny data sizes only: this checks that the scripts do not break with a
refactor, it does not measure anything. ab.sh needs uvicorn and Apache Bench,
so only its Python half (seed.py) is exercised here.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

PERF_DIR: Path = Path(__file__).resolve().parents[1] / "scripts" / "perf"
sys.path.insert(0, str(PERF_DIR))

import bench  # noqa: E402
import prof  # noqa: E402


async def test_bench_runs(capsys: pytest.CaptureFixture[str]) -> None:
    await bench.run(users=3, tasks_per_user=5, target_tasks=4, samples=2, bcrypt_rounds=4)
    out = capsys.readouterr().out

    assert "login: HTTP 200" in out
    assert "- GET /tasks: HTTP 200" in out
    assert "- DELETE /tasks/{id}: HTTP 204" in out
    assert "tareas devueltas: 4" in out
    assert "ix_tasks_owner_id" in out


async def test_prof_runs(capsys: pytest.CaptureFixture[str]) -> None:
    stats = await prof.profile(requests=5)
    prof.report(stats, requests=5, top=3)
    out = capsys.readouterr().out

    assert "tiempo por request" in out
    assert "sqlalchemy" in out


def test_seed_cli_prints_key_and_token(tmp_path: Path) -> None:
    db = tmp_path / "bench.db"
    result = subprocess.run(
        [sys.executable, str(PERF_DIR / "seed.py"), "--db", str(db), "--users", "2", "--tasks-per-user", "3"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    lines = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())

    assert set(lines) == {"SECRET_KEY", "TOKEN"}
    assert lines["TOKEN"].count(".") == 2
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT count(*) FROM tasks").fetchone() == (6,)
    finally:
        con.close()
