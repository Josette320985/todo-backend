from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Final

import bcrypt
from jose import jwt

from app.core.config import Settings

# Maximum password length supported by bcrypt (72 UTF-8 bytes).
MAX_BCRYPT_PASSWORD_BYTES: Final[int] = 72

@lru_cache
def dummy_password_hash(rounds: int) -> str:
    """
    Return a dummy bcrypt hash with the given cost, computed once per cost.

    Login verifies against it when the email does not exist, so the
    response takes as long as for a real user (mitigates timing attacks).
    It must use the same rounds as real password hashes.
    """
    return bcrypt.hashpw(
        b"dummy-timing-defense-password", bcrypt.gensalt(rounds)
    ).decode("utf-8")


def hash_password(password: str, rounds: int) -> str:
    """
    Generate a secure bcrypt hash from a plain-text password.

    Args:
        password (str): Plain-text password to hash (max 72 UTF-8 bytes).
        rounds (int): bcrypt cost factor (Settings.BCRYPT_ROUNDS).

    Returns:
        str: Hashed password suitable for database storage.

    Raises:
        ValueError: If the UTF-8 encoded password exceeds 72 bytes.
    """
    password_bytes: bytes = password.encode("utf-8")
    if len(password_bytes) > MAX_BCRYPT_PASSWORD_BYTES:
        raise ValueError("La contraseña no puede exceder 72 bytes en UTF-8")
    hashed_bytes: bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds))
    return hashed_bytes.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plain-text password against a stored bcrypt password hash.

    Safely returns False instead of raising ValueError if the input
    password exceeds 72 UTF-8 bytes or the stored hash is malformed.

    Args:
        plain (str): Password provided by the user.
        hashed (str): Previously stored password hash.

    Returns:
        bool: True if the password matches, otherwise False.
    """
    plain_bytes: bytes = plain.encode("utf-8")
    if len(plain_bytes) > MAX_BCRYPT_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(plain_bytes, hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, version: int, settings: Settings) -> str:
    """
    Generate a signed JWT access token for authentication.

    The token includes the subject identifier, the user's token version,
    issued-at timestamp, and an expiration timestamp based on the
    configured token lifetime.

    Args:
        subject (str): Identifier stored in the JWT subject claim.
        version (int): User's current token_version, stored in "ver".
        settings (Settings): App settings (secret key, algorithm, lifetime).

    Returns:
        str: Encoded and signed JWT access token.
    """
    now: datetime = datetime.now(timezone.utc)
    expire: datetime = now + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    # Define the JWT claims and sign the token.
    payload: dict[str, str | int | datetime] = {
        "sub": subject,
        "ver": version,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(
        payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
