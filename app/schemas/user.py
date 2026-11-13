from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """
    Schema for registering a new user.

    Validates the email address format and requires a password
    between 8 and 128 characters.
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    """
    Schema for returning user information in API responses.

    Includes the user's identifier and email address
    without exposing the stored password hash.
    """

    id: int
    email: EmailStr

    # Allow Pydantic to read data from SQLAlchemy model attributes.
    model_config = {"from_attributes": True}
