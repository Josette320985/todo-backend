from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

from app.core.emails import normalize_email

NormalizedEmail = Annotated[EmailStr, AfterValidator(normalize_email)]


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

    id: int
    email: EmailStr

    # Allow Pydantic to read data from SQLAlchemy model attributes.
    model_config = ConfigDict(from_attributes=True)
