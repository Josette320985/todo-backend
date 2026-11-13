from pydantic import BaseModel


class Token(BaseModel):
    """
    Schema for the authentication token response.

    Contains the JWT access token and its authentication type.
    The default token type is Bearer.
    """

    access_token: str
    token_type: str = "bearer"
