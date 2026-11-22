from collections import defaultdict, deque
import time
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import get_auth_service, get_current_user
from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository, get_user_repository
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserRead
from app.services.auth_service import AuthService

# Router responsible for user registration and authentication.
router: Final[APIRouter] = APIRouter(prefix="/auth", tags=["auth"])

# Sliding-window rate-limiting settings per client IP.
RATE_LIMIT_WINDOW_SECONDS: Final[float] = 60.0
MAX_LOGIN_ATTEMPTS_PER_WINDOW: Final[int] = 10
MAX_REGISTER_ATTEMPTS_PER_WINDOW: Final[int] = 5

_rate_limit_buckets: dict[str, deque[float]] = defaultdict(deque)


def _enforce_rate_limit(key: str, max_attempts: int) -> None:
    """
    Enforce a sliding-window rate limit for the given key.

    Raises HTTP 429 Too Many Requests when the limit is exceeded.
    """
    now: float = time.monotonic()
    bucket: deque[float] = _rate_limit_buckets[key]
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Intenta de nuevo en un minuto.",
        )
    bucket.append(now)


@router.post("/register", response_model=UserRead, status_code=201)
async def register(
    request: Request,
    payload: UserCreate,
    service: AuthService = Depends(get_auth_service),
) -> User:
    """
    Register a new user in the database.

    Enforces rate limiting and delegates validation, hashing and storage to
    the authentication service.

    Args:
        request (Request): Incoming HTTP request (used for rate limiting).
        payload (UserCreate): User registration data.
        service (AuthService): Registration and authentication use cases.

    Returns:
        User: The newly created user.

    Raises:
        HTTPException: If rate limit is exceeded (429).
        EmailAlreadyRegistered: If the email is already registered (400). The
            explicit message is intentional: SEG-H05 accepts email enumeration
            on registration, bounded by rate limiting and the generic login
            response.
    """
    client_ip: str = request.client.host if request.client else "unknown"
    _enforce_rate_limit(
        f"register:{client_ip}", MAX_REGISTER_ATTEMPTS_PER_WINDOW
    )
    return await service.register(payload)


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """
    Authenticate a user and generate a JWT access token.

    Enforces rate limiting, delegates credential verification to the
    authentication service, and creates the access token.

    Args:
        request (Request): Incoming HTTP request.
        form (OAuth2PasswordRequestForm): Login credentials.
        service (AuthService): Registration and authentication use cases.
        settings (Settings): Settings of the app handling the request.

    Returns:
        dict[str, str]: JWT access token and token type.

    Raises:
        HTTPException: If rate limit is exceeded (429).
        InvalidCredentials: If the credentials are invalid (401).
    """
    client_ip: str = request.client.host if request.client else "unknown"
    _enforce_rate_limit(f"login:{client_ip}", MAX_LOGIN_ATTEMPTS_PER_WINDOW)

    user: User = await service.authenticate(
        form.username, form.password, client_ip
    )
    return {
        "access_token": create_access_token(
            str(user.id), user.token_version, settings
        ),
        "token_type": "bearer",
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    user: User = Depends(get_current_user),
    users: UserRepository = Depends(get_user_repository),
) -> None:
    """Revoke every token issued to the current user (all sessions)."""
    user.token_version += 1
    await users.add(user)
