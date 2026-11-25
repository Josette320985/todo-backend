from typing import Final

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import (
    get_auth_service,
    get_current_user,
    get_email_validation_limiter,
    get_login_limiter,
    get_register_limiter,
)
from app.core.config import Settings, get_settings
from app.core.rate_limit import LoginRateLimiter, RateLimiter
from app.core.security import create_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository, get_user_repository
from app.schemas.user import (
    EmailValidationRequest, EmailValidationResult, UserCreate, UserRead,
    check_registration_email,
)
from app.services.auth_service import AuthService

# Router responsible for user registration and authentication.
router: Final[APIRouter] = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/validate-email", response_model=EmailValidationResult)
async def validate_registration_email(
    request: Request,
    payload: EmailValidationRequest,
    limiter: RateLimiter = Depends(get_email_validation_limiter),
) -> EmailValidationResult:
    """Validate syntax before registration, without creating or looking up users."""
    client_ip = request.client.host if request.client else "unknown"
    limiter.check(client_ip)
    return check_registration_email(payload.email)


@router.post("/register", response_model=UserRead, status_code=201)
async def register(
    request: Request,
    payload: UserCreate,
    service: AuthService = Depends(get_auth_service),
    limiter: RateLimiter = Depends(get_register_limiter),
) -> User:
    """
    Register a new user in the database.

    Enforces rate limiting and delegates validation, hashing and storage to
    the authentication service.

    Args:
        request (Request): Incoming HTTP request (used for rate limiting).
        payload (UserCreate): User registration data.
        service (AuthService): Registration and authentication use cases.
        limiter (RateLimiter): Registration limiter of the app.

    Returns:
        User: The newly created user.

    Raises:
        RateLimited: If the rate limit is exceeded (429).
        EmailAlreadyRegistered: If the email is already registered (400). The
            explicit message is intentional: SEG-H05 accepts email enumeration
            on registration, bounded by rate limiting and the generic login
            response.
    """
    client_ip: str = request.client.host if request.client else "unknown"
    limiter.check(client_ip)
    return await service.register(payload)


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
    limiter: LoginRateLimiter = Depends(get_login_limiter),
) -> dict[str, str]:
    """
    Authenticate a user and set the JWT access token in an HttpOnly cookie.
    """
    client_ip: str = request.client.host if request.client else "unknown"
    limiter.check(client_ip, form.username)

    user: User = await service.authenticate(
        form.username, form.password, client_ip
    )
    # Reached only with valid credentials: a failure raised above and its
    # attempt stays counted.
    limiter.succeeded(client_ip, form.username)
    token: str = create_access_token(str(user.id), user.token_version, settings)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT.strip().lower() == "production",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    return {"detail": "Sesión iniciada"}

@router.get("/me", response_model=UserRead)
async def read_current_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Return the authenticated user's public profile.

    UX-14 uses this endpoint to show the email in the navigation bar. The user
    is loaded by ``get_current_user``, which validates the JWT and the token
    version, so no password hash or other private field is exposed.

    Args:
        current_user (User): User resolved from the Bearer token.

    Returns:
        User: The authenticated user, serialized as ``UserRead``.

    Raises:
        HTTPException: If the token is invalid, expired or revoked (401).
    """
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,  # <-- 1. Agrega este parámetro
    user: User = Depends(get_current_user),
    users: UserRepository = Depends(get_user_repository),
    settings: Settings = Depends(get_settings),  # <-- 2. Agrega este parámetro
) -> None:
    """
    Revoke every token issued to the current user (all sessions).
    """
    user.token_version += 1
    await users.add(user)
    
    # 3. Borra la cookie del navegador
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path=settings.AUTH_COOKIE_PATH,
    )