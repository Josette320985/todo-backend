
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserRead

# Router responsible for user registration and authentication.
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=201)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
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
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    # Hash the password before storing the new user.
    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
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
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()

    # Reject invalid credentials.
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    # Generate and return the JWT access token.
    return {
        "access_token": create_access_token(str(user.id)),
        "token_type": "bearer",
    }
