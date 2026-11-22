"""Business rules for registration and login.

bcrypt is CPU-bound and runs in a worker thread, so the event loop keeps
serving other requests while a password is hashed or verified. The dummy hash
for unknown emails keeps the response time of a failed login similar to a real
one, which mitigates user enumeration by timing.
"""

import asyncio
import logging
from typing import Final

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import EmailAlreadyRegistered, InvalidCredentials
from app.core.logging import sanitize_for_log
from app.core.security import dummy_password_hash, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate

logger: Final[logging.Logger] = logging.getLogger("auth")


def _log_failed_login(email: str, client_ip: str) -> None:
    """Log a failed login without letting the input forge log lines."""
    logger.warning(
        "Failed login attempt | email=%s ip=%s",
        sanitize_for_log(email),
        sanitize_for_log(client_ip),
    )


class AuthService:
    """Registration and authentication use cases."""

    def __init__(self, users: UserRepository, settings: Settings) -> None:
        self._users = users
        self._settings = settings

    async def register(self, payload: UserCreate) -> User:
        """
        Register a new user.

        Raises:
            EmailAlreadyRegistered: If the email is already in use, including
                when a concurrent registration wins the race and the unique
                constraint is violated.
        """
        if await self._users.get_by_email(payload.email) is not None:
            raise EmailAlreadyRegistered()

        hashed: str = await asyncio.to_thread(
            hash_password, payload.password, self._settings.BCRYPT_ROUNDS
        )
        user: User = User(email=payload.email, hashed_password=hashed)
        try:
            return await self._users.add(user)
        except IntegrityError as exc:
            # Two concurrent registrations can both pass the pre-check. The
            # unique index on users.email is the source of truth; the
            # repository has already rolled back the failed transaction.
            raise EmailAlreadyRegistered() from exc

    async def authenticate(
        self, email: str, password: str, client_ip: str
    ) -> User:
        """
        Return the user when the credentials are valid.

        Args:
            email (str): Email submitted by the client.
            password (str): Plain-text password submitted by the client.
            client_ip (str): Origin of the request, for the failure log.

        Raises:
            InvalidCredentials: If the email does not exist or the password
                does not match.
        """
        normalized_email: str = email.strip().lower()
        user: User | None = await self._users.get_by_email(normalized_email)

        if user is None:
            dummy: str = await asyncio.to_thread(
                dummy_password_hash, self._settings.BCRYPT_ROUNDS
            )
            await asyncio.to_thread(verify_password, password, dummy)
            _log_failed_login(email, client_ip)
            raise InvalidCredentials()

        is_valid: bool = await asyncio.to_thread(
            verify_password, password, user.hashed_password
        )
        if not is_valid:
            _log_failed_login(email, client_ip)
            raise InvalidCredentials()

        return user
