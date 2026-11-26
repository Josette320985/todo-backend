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
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

DEFAULT_ERROR_CODE: Final[str] = "error"
VALIDATION_CODE: Final[str] = "validation_error"

FIELD_LABELS: Final[dict[str, str]] = {
    "title": "El título",
    "description": "La descripción",
    "password": "La contraseña",
    "email": "El email",
    "username": "El usuario",
    "completed": "El estado",
    "start_date": "La fecha de inicio",
    "end_date": "La fecha de término",
    "task_id": "El id de la tarea",
}

HTTP_ERRORS: Final[dict[int, tuple[str, str]]] = {
    400: ("Solicitud inválida", "bad_request"),
    401: ("No se pudieron validar las credenciales", "not_authenticated"),
    403: ("Acceso denegado", "forbidden"),
    404: ("Recurso no encontrado", "not_found"),
    405: ("Método no permitido", "method_not_allowed"),
    422: ("Datos inválidos", VALIDATION_CODE),
    429: ("Demasiados intentos. Intenta de nuevo en un minuto.", "rate_limit_exceeded"),
    500: ("Error interno del servidor", "internal_error"),
}

ENGLISH_HTTP_DETAILS: Final[frozenset[str]] = frozenset(
    {
        "bad request",
        "forbidden",
        "internal server error",
        "method not allowed",
        "not authenticated",
        "not found",
        "too many requests",
        "unauthorized",
    }
)


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


class TaskLimitReached(DomainError):
    """The user already has the maximum number of tasks (SEG-H12)."""

    status_code = 409
    code = "task_limit_reached"
    detail = "Alcanzaste el máximo de tareas permitido"


class EmailAlreadyRegistered(DomainError):
    """The email is already used by another account."""

    status_code = 400
    code = "email_already_registered"
    detail = "El email ya está registrado"


class DirectoryUnavailable(DomainError):
    """The LDAP directory could not be queried (F1)."""

    status_code = 503
    code = "directory_unavailable"
    detail = "El directorio de autenticación no está disponible. Intenta de nuevo."


class InvalidCredentials(DomainError):
    """The email/password pair does not match an account."""

    status_code = 401
    code = "invalid_credentials"
    detail = "Credenciales incorrectas"
    headers = {"WWW-Authenticate": "Bearer"}


class RateLimited(DomainError):
    """Too many attempts in the current window (ARQ-05).

    ``retry_after`` is the whole seconds until the client may try again. It is
    also sent in the ``Retry-After`` header (ERR-03), which the frontend turns
    into the countdown.
    """

    status_code = 429
    code = "rate_limit_exceeded"
    detail = "Demasiados intentos. Intenta de nuevo en un minuto."

    def __init__(self, retry_after: int, detail: str | None = None) -> None:
        super().__init__(detail, headers={"Retry-After": str(retry_after)})
        self.retry_after: int = retry_after


def domain_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Translate a DomainError into its JSON response."""
    error: DomainError = exc if isinstance(exc, DomainError) else DomainError()
    return JSONResponse(
        status_code=error.status_code,
        content=error.to_dict(),
        headers=dict(error.headers) if error.headers else None,
    )


def _error_field(error: Mapping[str, Any]) -> str:
    """Return the API field name from a Pydantic error location."""
    location: Sequence[Any] = error.get("loc") or ()
    parts: list[str] = [
        str(part) for part in location if not isinstance(part, int)
    ]
    return parts[-1] if parts else "general"


def _validation_message(error: Mapping[str, Any], field: str) -> str:
    """Translate one Pydantic error into a Spanish, user-facing message."""
    error_type: str = str(error.get("type", ""))
    context: Mapping[str, Any] = error.get("ctx") or {}
    label: str = FIELD_LABELS.get(field, field)

    if error_type == "missing":
        return f"{label} es obligatorio"

    if error_type == "string_too_short":
        minimum: int = context.get("min_length", 1)
        noun: str = "carácter" if minimum == 1 else "caracteres"
        return f"{label} debe tener al menos {minimum} {noun}"

    if error_type == "string_too_long":
        maximum: int = context.get("max_length", 0)
        return f"{label} no puede superar {maximum} caracteres"

    if error_type == "json_invalid":
        return "El cuerpo de la petición no es un JSON válido"

    if error_type.startswith("date_") or error_type.startswith("datetime_"):
        return f"{label} debe ser una fecha válida"

    if error_type in {"int_parsing", "int_from_float", "int_type"}:
        return f"{label} debe ser un número entero"

    if error_type in {"bool_parsing", "bool_type"}:
        return f"{label} debe ser verdadero o falso"

    if error_type == "greater_than_equal":
        return f"{label} debe ser mayor o igual que {context.get('ge', 0)}"

    if error_type == "less_than_equal":
        return f"{label} debe ser menor o igual que {context.get('le', 0)}"

    if error_type == "value_error":
        message: str = str(error.get("msg", ""))
        if message.startswith("Value error, "):
            message = message[len("Value error, ") :]
        lowered: str = message.lower()
        if "email address" in lowered or "is not a valid" in lowered:
            return f"{label} no es válido"
        if message:
            return message
        return "Los datos no son válidos" if field == "general" else f"{label} no es válido"

    if field == "general":
        return "Los datos no son válidos"
    return f"{label} no es válido"


def _validation_detail(error: Mapping[str, Any]) -> tuple[str, str]:
    """Return the field and Spanish message for a Pydantic error."""
    field: str = _error_field(error)
    message: str = _validation_message(error, field)
    if error.get("type") == "json_invalid":
        field = "body"
    elif field == "general" and "fecha" in message.lower():
        field = "end_date"
    return field, message


def request_validation_error_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    """Translate FastAPI validation errors into the single error format."""
    validation_error: RequestValidationError = (
        exc
        if isinstance(exc, RequestValidationError)
        else RequestValidationError([])
    )
    details: list[tuple[str, str]] = [
        _validation_detail(error) for error in validation_error.errors()
    ]
    detail: str = details[0][1] if details else "Datos inválidos"
    return JSONResponse(
        status_code=422,
        content={
            "detail": detail,
            "code": VALIDATION_CODE,
            "errors": [
                {"field": field, "message": message} for field, message in details
            ],
        },
    )


def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Translate Starlette HTTP exceptions into the single error format."""
    http_error: StarletteHTTPException = (
        exc
        if isinstance(exc, StarletteHTTPException)
        else StarletteHTTPException(status_code=500)
    )
    detail, code = HTTP_ERRORS.get(
        http_error.status_code,
        ("No se pudo completar la operación", DEFAULT_ERROR_CODE),
    )
    raw_detail: Any = http_error.detail
    if (
        isinstance(raw_detail, str)
        and raw_detail.strip()
        and raw_detail.strip().lower() not in ENGLISH_HTTP_DETAILS
    ):
        detail = raw_detail.strip()
    return JSONResponse(
        status_code=http_error.status_code,
        content={"detail": detail, "code": code},
        headers=dict(http_error.headers) if http_error.headers else None,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the handlers that build every API error response."""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(
        RequestValidationError, request_validation_error_handler
    )
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
