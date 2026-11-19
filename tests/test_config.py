"""Tests for SECRET_KEY validation in app.core.config."""

import secrets

import pytest
from pydantic import ValidationError

from app.core.config import Settings

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
