"""Domain exceptions and the handlers that translate them to HTTP.

Services raise exceptions that describe the business problem (a task does not
exist, the email is taken, the credentials are wrong) without knowing about
status codes. The handlers in this module are the only place that maps them
to a JSON response, so every endpoint answers errors in the same shape.

This is the base for ERR-01 (catch-all handler) and ERR-02 (single error
format): both only add to this file.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DEFAULT_ERROR_CODE: Final[str] = "error"


@dataclass(frozen=True)
class ErrorDetail:
    """One invalid field, in the shape the API returns it."""

    field: str
    message: str


class DomainError(Exception):
    """Base class for errors caused by the business rules."""

    status_code: int = 400
    code: str = DEFAULT_ERROR_CODE
    detail: str = "No se pudo completar la operación"
    headers: Mapping[str, str] | None = None

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: Sequence[ErrorDetail] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.detail = detail if detail is not None else type(self).detail
        self.errors: list[ErrorDetail] = list(errors) if errors else []
        self.headers = headers if headers is not None else type(self).headers
        super().__init__(self.detail)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON body for this error."""
        body: dict[str, Any] = {"detail": self.detail, "code": self.code}
        if self.errors:
            body["errors"] = [
                {"field": item.field, "message": item.message}
                for item in self.errors
            ]
        return body


class NotFoundError(DomainError):
    """The resource does not exist or does not belong to the caller."""

    status_code = 404
    code = "not_found"
    detail = "Recurso no encontrado"


class ValidationFailed(DomainError):
    """A business rule rejected the data (for example, an invalid date range)."""

    status_code = 422
    code = "validation_error"
    detail = "Datos inválidos"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message, errors=[ErrorDetail(field, message)])


class EmailAlreadyRegistered(DomainError):
    """The email is already used by another account."""

    status_code = 400
    code = "email_already_registered"
    detail = "El email ya está registrado"


class InvalidCredentials(DomainError):
    """The email/password pair does not match an account."""

    status_code = 401
    code = "invalid_credentials"
    detail = "Credenciales incorrectas"
    headers = {"WWW-Authenticate": "Bearer"}


def domain_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Translate a DomainError into its JSON response."""
    error: DomainError = exc if isinstance(exc, DomainError) else DomainError()
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
        headers=dict(error.headers) if error.headers else None,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the domain error handlers on the application."""
    app.add_exception_handler(DomainError, domain_error_handler)
