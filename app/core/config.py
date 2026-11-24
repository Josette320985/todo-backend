from functools import lru_cache
from typing import ClassVar, Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables.

    Defines database connection settings and JWT authentication
    parameters. Values can be overridden through environment
    variables or the configured .env file.
    """

    # Database connection URL (SQLite by default).
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/todo.db"

    # Secret key used to sign and validate JWT access tokens (min 32 chars).
    SECRET_KEY: str = Field(min_length=32)

    # JWT access token expiration time in minutes (1 min to 24 hours).
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)

    # bcrypt cost factor (2^rounds iterations). 12 in production; tests use
    # the minimum (4) so hashing does not dominate the suite's run time.
    BCRYPT_ROUNDS: int = Field(default=12, ge=4, le=31)

    # Algorithm used for JWT signing and verification (restricted to HS256).
    ALGORITHM: Literal["HS256"] = "HS256"

    # Deployment environment ("development" or "production").
    ENVIRONMENT: str = "development"

    # Minimum level emitted by the application and uvicorn loggers.
    LOG_LEVEL: str = "INFO"

    # Expose Prometheus HTTP metrics on /metrics (keep internal behind proxy).
    METRICS_ENABLED: bool = True

    # Allowed CORS origins for the frontend application.
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ]

    # Public placeholder values that must never reach a running deployment.
    _KNOWN_PLACEHOLDERS: ClassVar[frozenset[str]] = frozenset(
        {
            "reemplaza-esta-clave-por-una-larga-y-aleatoria-de-al-menos-32-caracteres",
        }
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        stripped: str = value.strip()
        if len(stripped) < 32:
            raise ValueError(
                "SECRET_KEY debe tener al menos 32 caracteres no vacíos; "
                "genere uno con secrets.token_urlsafe(48)"
            )
        if (
            stripped in cls._KNOWN_PLACEHOLDERS
            or "reemplaza" in stripped.lower()
            or len(set(stripped)) < 16
        ):
            raise ValueError(
                "SECRET_KEY es un valor de ejemplo o débil; "
                "genere uno con secrets.token_urlsafe(48)"
            )
        return stripped

    # Load environment variables from .env and ignore extra settings.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """
    Return the settings loaded from the environment and the .env file.

    Cached so the environment is read once per process. Endpoints receive
    settings through Depends(get_settings); create_app() overrides this
    dependency with the Settings it was given, so tests can build apps
    with their own configuration without touching environment variables.
    """
    try:
        return Settings()
    except ValidationError as exc:
        # ERR-09: one readable line instead of a Pydantic traceback.
        raise SystemExit(describe_settings_error(exc)) from None


# How to produce a valid SECRET_KEY, shown when it is missing or rejected.
SECRET_KEY_HINT: str = (
    'genera una con: python -c "import secrets; print(secrets.token_urlsafe(48))"'
)


def describe_settings_error(exc: ValidationError) -> str:
    """
    Summarize a Settings validation error in a single line (ERR-09).

    Names each variable that is missing or invalid and, for SECRET_KEY,
    how to generate one. The rejected values are never included, so a
    real secret cannot leak into the logs.
    """
    problems: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        name: str = ".".join(str(part) for part in error["loc"]) or "configuración"
        if error["type"] == "missing":
            problem = f"falta {name}"
            if name == "SECRET_KEY":
                problem += f" en el entorno o en .env; {SECRET_KEY_HINT}"
        else:
            reason: str = error["msg"].removeprefix("Value error, ")
            problem = f"{name} no es válida: {reason}"
        problems.append(problem)
    return "Error de configuración: " + "; ".join(problems)
