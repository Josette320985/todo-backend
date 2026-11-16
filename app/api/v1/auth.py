import logging
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import Result, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserRead

# Router responsible for user registration and authentication.
router: Final[APIRouter] = APIRouter(prefix="/auth", tags=["auth"])
# Structured logger for security-relevant auth events.
logger: Final[logging.Logger] = logging.getLogger("auth")
@router.post("/register", response_model=UserRead, status_code=201)
async def register(
    payload: UserCreate, db: AsyncSession = Depends(get_db)
) -> User:
    """
    Register a new user in the database.

    Checks whether the email is already registered, hashes the
    provided password, and stores the new user.

    Args:
        payload (UserCreate): User registration data.
        db (AsyncSession): Asynchronous database session.

    Returns:
        User: The newly created user.

    Raises:
        HTTPException: If the email is already registered (400).
    """
    # Check whether a user with the provided email already exists.
    existing: Result[tuple[User]] = await db.execute(
        select(User).where(User.email == payload.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    # Hash the password before storing the new user.
    user: User = User(
        email=payload.email, hashed_password=hash_password(payload.password)
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Authenticate a user and generate a JWT access token.

    Retrieves the user by email, verifies the submitted password,
    and creates an access token after successful authentication.

    Args:
        form (OAuth2PasswordRequestForm): Login credentials.
        db (AsyncSession): Asynchronous database session.

    Returns:
        dict: JWT access token and token type.

    Raises:
        HTTPException: If the credentials are invalid (401).
    """
    # Retrieve the user associated with the submitted email.
    result: Result[tuple[User]] = await db.execute(
        select(User).where(User.email == form.username)
    )
    user: User | None = result.scalar_one_or_none()

    if not user or not verify_password(form.password, user.hashed_password):
        client_ip: str = request.client.host if request.client else "unknown"
        logger.warning(
            "Failed login attempt | email=%s ip=%s",
            form.username,
            client_ip,
        )
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")
    # Generate and return the JWT access token.
    return {
        "access_token": create_access_token(str(user.id)),
        "token_type": "bearer",
    }
