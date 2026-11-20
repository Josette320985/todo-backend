from typing import Any, Final

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.core.config import Settings, get_settings
from app.models.user import User
from app.repositories.user_repository import UserRepository, get_user_repository

# Extract the Bearer token from the Authorization header.
# The token URL identifies the authentication endpoint.
oauth2_scheme: Final[OAuth2PasswordBearer] = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login"
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> User:
    """
    Validate a JWT access token and retrieve the authenticated user.

    Decodes the token using the configured secret key and algorithm,
    requires both 'sub' and 'exp' claims, extracts the integer user ID,
    and verifies that the corresponding user exists in the database.

    Args:
        token (str): JWT access token extracted from the request.
        users (UserRepository): Data access for users.
        settings (Settings): Settings of the app handling the request.

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
    user: User | None = await users.get_by_id(parsed_user_id)

    # Reject if the user no longer exists or the token was revoked (logout).
    if user is None or payload.get("ver") != user.token_version:
        raise credentials_exception

    return user
