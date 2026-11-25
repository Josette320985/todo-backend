import re
from typing import Annotated
import uuid

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from app.core.emails import normalize_email

NormalizedEmail = Annotated[EmailStr, AfterValidator(normalize_email)]
_email_adapter: TypeAdapter[str] = TypeAdapter(NormalizedEmail)


class EmailValidationRequest(BaseModel):
    email: str = Field(max_length=2048)


class EmailValidationResult(BaseModel):
    valid: bool
    normalized: str | None = None
    message: str | None = None


def check_registration_email(value: str) -> EmailValidationResult:
    """Use the registration field itself; never query account availability or DNS."""
    try:
        normalized = _email_adapter.validate_python(value)
    except (ValidationError, ValueError):
        return EmailValidationResult(valid=False, message="El email no es válido")
    return EmailValidationResult(valid=True, normalized=normalized)


class UserCreate(BaseModel):
    """
    Schema for registering a new user.

    Validates and normalizes the email address (Unicode/IDN) and requires a
    password between 8 and 72 characters ( maximum 72 UTF-8 bytes for bcrypt )
    containing at least one letter and one digit.
    """

    email: NormalizedEmail
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        # Accept client-side SHA-256 hex digests (64 lowercase hex chars, 64 bytes <= 72).
        if re.fullmatch(r"[0-9a-f]{64}", value):
            return value
        if len(value.encode("utf-8")) > 72:
            raise ValueError(
                "La contraseña no puede exceder 72 bytes en codificación UTF-8"
            )
        if not value.strip():
            raise ValueError(
                "La contraseña no puede contener únicamente espacios"
            )
        if not any(ch.isalpha() for ch in value) or not any(
            ch.isdigit() for ch in value
        ):
            raise ValueError(
                "La contraseña debe incluir al menos una letra y un número"
            )
        return value


class UserRead(BaseModel):
    """
    Schema for returning user information in API responses.

    Includes the user's identifier and email address
    without exposing the stored password hash.
    """

    id: uuid.UUID
    email: EmailStr

    # Allow Pydantic to read data from SQLAlchemy model attributes.
    model_config = ConfigDict(from_attributes=True)
