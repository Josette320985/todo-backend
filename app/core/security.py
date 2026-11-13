from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

# Configure bcrypt for secure password hashing and verification.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    Generate a secure hash from a plain-text password.

    Args:
        password (str): Plain-text password to hash.

    Returns:
        str: Hashed password suitable for database storage.
    """
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify a plain-text password against a stored password hash.

    Args:
        plain (str): Password provided by the user.
        hashed (str): Previously stored password hash.

    Returns:
        bool: True if the password matches, otherwise False.
    """
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str) -> str:
    """
    Generate a signed JWT access token for authentication.

    The token includes the subject identifier and an expiration
    timestamp based on the configured token lifetime.

    Args:
        subject (str): Identifier stored in the JWT subject claim.

    Returns:
        str: Encoded and signed JWT access token.
    """
    # Calculate the expiration timestamp using UTC.
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )

    # Define the JWT claims and sign the token.
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
