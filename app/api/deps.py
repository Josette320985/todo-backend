from typing import Any, Final
import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt

from app.core.config import Settings, get_settings
from app.core.rate_limit import RateLimiter, LoginRateLimiter
from app.models.user import User
from app.repositories.task_repository import TaskRepository, get_task_repository
from app.repositories.user_repository import UserRepository, get_user_repository
from app.services.auth_service import AuthService
from app.services.task_service import TaskService

# Extract the Bearer token from the Authorization header when present
# (fallback alongside the HttpOnly access_token cookie).
oauth2_scheme: Final[OAuth2PasswordBearer] = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)


async def get_current_user(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> User:
    """
    Validate a JWT access token (from HttpOnly cookie or Bearer header) and
    retrieve the authenticated user.

    Decodes the token using the configured secret key and algorithm,
    requires both 'sub' and 'exp' claims, extracts the UUID user ID,
    and verifies that the corresponding user exists in the database.
    """
    # Define the HTTP 401 response for invalid credentials.
    credentials_exception: HTTPException = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token: str | None = bearer_token or request.cookies.get("access_token")
    if not token:
        raise credentials_exception

    # Decode the JWT and extract the user UUID from the subject claim.
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
        raw_sub: Any = payload.get("sub")
        if not isinstance(raw_sub, str):
            raise credentials_exception
        parsed_user_id: uuid.UUID = uuid.UUID(raw_sub)
    except (jwt.PyJWTError, ValueError, TypeError):
        raise credentials_exception

    # Retrieve the user associated with the validated token.
    user: User | None = await users.get_by_id(parsed_user_id)

    # Reject if the user no longer exists or the token was revoked (logout).
    if user is None or payload.get("ver") != user.token_version:
        raise credentials_exception

    return user


def get_task_service(
    tasks: TaskRepository = Depends(get_task_repository),
) -> TaskService:
    """FastAPI dependency: a TaskService bound to the request's repository."""
    return TaskService(tasks)


def get_auth_service(
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    """FastAPI dependency: an AuthService bound to the request's repository."""
    return AuthService(users, settings)

# --- Funciones nuevas (al final del archivo, después de get_auth_service) ---
def get_login_limiter(request: Request) -> LoginRateLimiter:
    """FastAPI dependency: the failed-login limiter of the app (ARQ-05, SEG-02)."""
    limiter: LoginRateLimiter = request.app.state.login_limiter
    return limiter


def get_register_limiter(request: Request) -> RateLimiter:
    """FastAPI dependency: the registration rate limiter of the app (ARQ-05)."""
    limiter: RateLimiter = request.app.state.register_limiter
    return limiter

def get_email_validation_limiter(request: Request) -> RateLimiter:
    """FastAPI dependency: the email validation rate limiter of the app."""
    limiter: RateLimiter = request.app.state.email_validation_limiter
    return limiter