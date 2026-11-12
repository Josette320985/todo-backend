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

    # Secret key used to sign and validate JWT access tokens.
    SECRET_KEY: str

    # JWT access token expiration time in minutes.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Algorithm used for JWT signing and verification.
    ALGORITHM: str = "HS256"

    # Load environment variables from .env and ignore extra settings.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Create a shared application settings instance.
settings = Settings()
