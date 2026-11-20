from collections import defaultdict, deque
import logging
import time
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.core.config import Settings, get_settings
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository, get_user_repository
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserRead

# Router responsible for user registration and authentication.
router: Final[APIRouter] = APIRouter(prefix="/auth", tags=["auth"])

# Structured logger for security-relevant auth events.
logger: Final[logging.Logger] = logging.getLogger("auth")

# Sliding-window rate-limiting settings per client IP.
RATE_LIMIT_WINDOW_SECONDS: Final[float] = 60.0
MAX_LOGIN_ATTEMPTS_PER_WINDOW: Final[int] = 10
MAX_REGISTER_ATTEMPTS_PER_WINDOW: Final[int] = 5

_rate_limit_buckets: dict[str, deque[float]] = defaultdict(deque)


def _sanitize_for_log(value: str, max_len: int = 120) -> str:
    """Escape control/non-ASCII characters (CR/LF, ANSI, U+2028...) and truncate."""
    return value.encode("unicode_escape").decode("ascii")[:max_len]


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
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> User:
    """
    Register a new user in the database.

    Enforces rate limiting, checks whether the email is already registered,
    hashes the provided password, and stores the new user.

    Args:
        request (Request): Incoming HTTP request (used for rate limiting).
        payload (UserCreate): User registration data.
        users (UserRepository): Data access for users.
        settings (Settings): Settings of the app handling the request.

    Returns:
        User: The newly created user.

    Raises:
        HTTPException: If rate limit is exceeded (429) or the email is
            already registered (400).
    """
    client_ip: str = request.client.host if request.client else "unknown"
    _enforce_rate_limit(
        f"register:{client_ip}", MAX_REGISTER_ATTEMPTS_PER_WINDOW
    )

    # Check whether a user with the provided email already exists.
    if await users.get_by_email(payload.email) is not None:
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    # Hash the password before storing the new user. bcrypt is CPU-bound and
    # blocks for ~0.25 s at the production cost, so it runs in a thread: the
    # event loop keeps serving other requests meanwhile (SEG-H03).
    user: User = User(
        email=payload.email,
        hashed_password=await run_in_threadpool(
            hash_password, payload.password, settings.BCRYPT_ROUNDS
        ),
    )
    return await users.add(user)


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    """
    Authenticate a user and generate a JWT access token.

    Enforces rate limiting, retrieves the user by normalized email,
    verifies the submitted password in constant-ish time (using a dummy
    bcrypt hash when the user does not exist), and creates an access token.

    Args:
        request (Request): Incoming HTTP request.
        form (OAuth2PasswordRequestForm): Login credentials.
        users (UserRepository): Data access for users.
        settings (Settings): Settings of the app handling the request.

    Returns:
        dict[str, str]: JWT access token and token type.

    Raises:
        HTTPException: If rate limit is exceeded (429) or credentials are
            invalid (401).
    """
    client_ip: str = request.client.host if request.client else "unknown"
    _enforce_rate_limit(f"login:{client_ip}", MAX_LOGIN_ATTEMPTS_PER_WINDOW)

    normalized_email: str = form.username.strip().lower()

    # Retrieve the user associated with the submitted email.
    user: User | None = await users.get_by_email(normalized_email)

    if user is None:
        # Run a dummy bcrypt verification to prevent user enumeration by timing.
        # Both calls go to a thread: the hash is cached, but the first one costs
        # a full bcrypt run and must not freeze the loop.
        await run_in_threadpool(
            verify_password,
            form.password,
            await run_in_threadpool(
                dummy_password_hash, settings.BCRYPT_ROUNDS
            ),
        )
        is_valid: bool = False
    else:
        is_valid = await run_in_threadpool(
            verify_password, form.password, user.hashed_password
        )

    if not is_valid or user is None:
        logger.warning(
            "Failed login attempt | email=%s ip=%s",
            _sanitize_for_log(form.username),
            _sanitize_for_log(client_ip),
        )
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    # Generate and return the JWT access token.
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
