from typing import Any, Final

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import Result, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

# Extract the Bearer token from the Authorization header.
# The token URL identifies the authentication endpoint.
oauth2_scheme: Final[OAuth2PasswordBearer] = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login"
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate a JWT access token and retrieve the authenticated user.

    Decodes the token using the configured secret key and algorithm,
    requires both 'sub' and 'exp' claims, extracts the integer user ID,
    and verifies that the corresponding user exists in the database.

    Args:
        token (str): JWT access token extracted from the request.
        db (AsyncSession): Asynchronous database session.

    Returns:
        User: The authenticated user retrieved from the database.

    Raises:
        HTTPException: If the token is invalid, expired, its subject is
            missing or malformed, or the associated user does not exist (401).
    """
    # Define the HTTP 401 response for invalid credentials.
    credentials_exception: HTTPException = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Decode the JWT and extract the numeric user ID from the subject claim.
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require_sub": True, "require_exp": True},
        )
        raw_sub: Any = payload.get("sub")
        if not isinstance(raw_sub, str):
            raise credentials_exception
        parsed_user_id: int = int(raw_sub)
    except (JWTError, ValueError, TypeError):
        raise credentials_exception

    # Retrieve the user associated with the validated token.
    result: Result[tuple[User]] = await db.execute(
        select(User).where(User.id == parsed_user_id)
    )
    user: User | None = result.scalar_one_or_none()

    # Reject authentication if the user no longer exists.
    if user is None:
        raise credentials_exception

    return user
