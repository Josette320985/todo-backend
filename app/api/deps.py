from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

# Extract the Bearer token from the Authorization header.
# The token URL identifies the authentication endpoint.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate a JWT access token and retrieve the authenticated user.

    Decodes the token using the configured secret key and algorithm,
    extracts the user ID from the subject claim, and verifies that
    the corresponding user exists in the database.

    Args:
        token (str): JWT access token extracted from the request.
        db (AsyncSession): Asynchronous database session.

    Returns:
        User: The authenticated user retrieved from the database.

    Raises:
        HTTPException: If the token is invalid, its subject is missing,
            or the associated user does not exist (401).
    """
    # Define the HTTP 401 response for invalid credentials.
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Decode the JWT and extract the user ID from the subject claim.
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # Retrieve the user associated with the validated token.
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    # Reject authentication if the user no longer exists.
    if user is None:
        raise credentials_exception

    return user
