from typing import Final, Literal

from pydantic import Field, field_validator
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

    # Algorithm used for JWT signing and verification (restricted to HS256).
    ALGORITHM: Literal["HS256"] = "HS256"

    # Deployment environment ("development" or "production").
    ENVIRONMENT: str = "development"

    # Allowed CORS origins for the frontend application.
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ]

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        stripped: str = value.strip()
        if len(stripped) < 32:
            raise ValueError(
                "SECRET_KEY debe tener al menos 32 caracteres no vacíos"
            )
        return stripped

    # Load environment variables from .env and ignore extra settings.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Create a shared application settings instance.
settings: Final[Settings] = Settings()
