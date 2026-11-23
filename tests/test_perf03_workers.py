"""
PERF-03: the backend runs with several Uvicorn workers.

Static checks (always run): the Dockerfile configures 4 workers through
WEB_CONCURRENCY and keeps --proxy-headers / --forwarded-allow-ips, and the SQLite
PRAGMAs that make several processes safe (OPT-05) are still there.

Live checks (marker "slow"): start the real app with uvicorn --workers 4 on a
throwaway database and check that (a) 4 worker processes are running, (b) a burst
of concurrent GET and POST requests has no errors and no "database is locked",
and (c) the login rate limit is shared between workers (BUG-02).

Run the live checks with:  pytest tests/test_perf03_workers.py -m slow
"""

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
WORKERS = 4
PASSWORD = "Str0ng-Passw0rd!"


# --------------------------------------------------------------------------- static


def dockerfile_text() -> str:
    return (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")


def test_dockerfile_sets_four_workers_by_environment_variable() -> None:
    match = re.search(r"^ENV\s+WEB_CONCURRENCY[= ](\d+)\s*$", dockerfile_text(), re.MULTILINE)
    assert match, "Dockerfile must define ENV WEB_CONCURRENCY"
    assert int(match.group(1)) == WORKERS


def test_cmd_does_not_hardcode_workers() -> None:
    cmd = re.search(r"^CMD\s*(\[.*\])\s*$", dockerfile_text(), re.MULTILINE)
    assert cmd, "Dockerfile needs an exec-form CMD"
    args: list[str] = json.loads(cmd.group(1))
    assert not any(a.startswith("--workers") for a in args), (
        "--workers on the CMD would override WEB_CONCURRENCY"
    )
    assert args[0] == "uvicorn"


def test_cmd_keeps_proxy_headers_for_nginx() -> None:
    cmd = re.search(r"^CMD\s*(\[.*\])\s*$", dockerfile_text(), re.MULTILINE)
    assert cmd
    args: list[str] = json.loads(cmd.group(1))
    assert "--proxy-headers" in args
    assert any(a.startswith("--forwarded-allow-ips=") and "*" not in a for a in args)


def test_wal_prerequisite_is_configured() -> None:
    source = (BACKEND_DIR / "app" / "db" / "session.py").read_text(encoding="utf-8")
    assert "PRAGMA journal_mode=WAL" in source


def test_compose_does_not_override_the_command() -> None:
    compose = (BACKEND_DIR / "docker-compose.yml").read_text(encoding="utf-8")
    assert not re.search(r"^\s*command:", compose, re.MULTILINE)


# ------------------------------------------------------------------------------ live


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def child_pids(parent: int) -> list[int]:
    """Direct children of a process (Linux /proc)."""
    out: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
        if ppid == parent:
            out.append(int(entry.name))
    return out


def request(
    method: str,
    url: str,
    *,
    body: dict[str, str] | None = None,
    form: dict[str, str] | None = None,
    token: str | None = None,
) -> tuple[int, str]:
    data: bytes | None = None
    headers = {"Connection": "close"}  # new connection per request: spreads over workers
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


class Server:
    def __init__(self, base: str, pid: int) -> None:
        self.base = base
        self.pid = pid

    def url(self, path: str) -> str:
        return f"{self.base}/api{path}"

    def login(self, email: str, password: str = PASSWORD) -> tuple[int, str]:
        return request("POST", self.url("/v1/auth/login"), form={"username": email, "password": password})


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Server]:
    if not sys.platform.startswith("linux"):
        pytest.skip("needs /proc to count worker processes")
    port = free_port()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'perf03.db'}",
        # Random: SEG-01 rejects repetitive keys, and the app would not start.
        "SECRET_KEY": secrets.token_urlsafe(48),
        "ENVIRONMENT": "production",
        "WEB_CONCURRENCY": str(WORKERS),  # what the Dockerfile ENV provides
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--log-level", "warning", "--no-access-log"],
        cwd=BACKEND_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"uvicorn exited early:\n{proc.stdout.read() if proc.stdout else ''}")
            try:
                if request("GET", f"{base}/api/health/ready")[0] == 200:
                    break
            except OSError:
                time.sleep(0.3)
        else:
            pytest.fail("uvicorn did not become ready in 60 s")
        yield Server(base, proc.pid)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def register_and_login(srv: Server, email: str) -> str:
    status, text = request("POST", srv.url("/v1/auth/register"), body={"email": email, "password": PASSWORD})
    assert status == 201, text
    status, text = srv.login(email)
    assert status == 200, text
    return str(json.loads(text)["access_token"])


@pytest.mark.slow
def test_four_worker_processes_are_running(server: Server) -> None:
    assert len(child_pids(server.pid)) >= WORKERS


@pytest.mark.slow
def test_concurrent_reads_and_writes_have_no_errors(server: Server) -> None:
    tokens = [register_and_login(server, f"user{i}@example.com") for i in range(4)]

    def create(i: int) -> tuple[int, str]:
        return request("POST", server.url("/v1/tasks/"), body={"title": f"task {i}"}, token=tokens[i % 4])

    def read(i: int) -> tuple[int, str]:
        return request("GET", server.url("/v1/tasks/"), token=tokens[i % 4])

    with ThreadPoolExecutor(max_workers=32) as pool:
        writes = list(pool.map(create, range(200)))
        mixed = list(pool.map(lambda i: create(i) if i % 2 else read(i), range(200)))

    failures = [(s, t) for s, t in writes + mixed if s not in (200, 201)]
    assert not failures, failures[:3]
    assert not any("database is locked" in t for _, t in writes + mixed)

    # Every write was stored: 200 creates + 100 creates in the mixed round.
    total = sum(
        len(json.loads(request("GET", server.url("/v1/tasks/"), token=t)[1])) for t in tokens
    )
    assert total == 300


@pytest.mark.slow
def test_login_rate_limit_is_shared_between_workers(server: Server) -> None:
    # Distinct emails: only the per-IP limit (10/min) applies, not the per-pair
    # one. Sent all at once: one request after another tends to land on the same
    # worker, which hides per-process counters; a burst spreads over all four.
    def attempt(i: int) -> int:
        return server.login(f"nobody{i}@example.com", "wrong-password-1")[0]

    with ThreadPoolExecutor(max_workers=40) as pool:
        statuses = list(pool.map(attempt, range(40)))

    assert statuses.count(401) == 10, statuses
    assert statuses.count(429) == 30, statuses