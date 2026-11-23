"""Tests for SECRET_KEY validation in app.core.config."""

import os
import secrets
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings

EXAMPLE_KEY = "reemplaza-esta-clave-por-una-larga-y-aleatoria-de-al-menos-32-caracteres"


def make_settings(secret_key: str) -> Settings:
    """Build Settings from explicit values, ignoring any local .env file."""
    return Settings(_env_file=None, SECRET_KEY=secret_key)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "secret_key",
    [
        EXAMPLE_KEY,  # published placeholder
        "REEMPLAZA-esta-clave-por-una-larga-y-aleatoria-de-al-menos-32-caracteres",
        "a" * 40,  # too little entropy
        "corta",  # too short
    ],
)
def test_rejects_weak_or_example_secret_key(secret_key: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(secret_key)


def test_accepts_random_secret_key() -> None:
    assert make_settings(secrets.token_urlsafe(48)).SECRET_KEY


# ERR-09: a bad configuration stops the app with one readable line.
BACKEND_ROOT: Path = Path(__file__).resolve().parents[1]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """No SECRET_KEY in the environment and no .env in the working dir."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_missing_secret_key_exits_with_one_line(clean_env: None) -> None:
    with pytest.raises(SystemExit) as exc_info:
        get_settings()
    message = str(exc_info.value.code)
    assert "\n" not in message
    assert "falta SECRET_KEY" in message
    assert "secrets.token_urlsafe(48)" in message


def test_invalid_secret_key_names_it_without_leaking_it(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SECRET_KEY", EXAMPLE_KEY)
    with pytest.raises(SystemExit) as exc_info:
        get_settings()
    message = str(exc_info.value.code)
    assert message.startswith("Error de configuración: SECRET_KEY no es válida")
    assert EXAMPLE_KEY not in message


def test_reports_every_invalid_variable(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "0")
    with pytest.raises(SystemExit) as exc_info:
        get_settings()
    message = str(exc_info.value.code)
    assert "falta SECRET_KEY" in message
    assert "ACCESS_TOKEN_EXPIRE_MINUTES no es válida" in message


def test_uvicorn_entry_point_prints_no_traceback(tmp_path: Path) -> None:
    env = {key: value for key, value in os.environ.items() if key != "SECRET_KEY"}
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", "import app.main as main; main.app"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert result.stderr.strip().startswith("Error de configuración: falta SECRET_KEY")
