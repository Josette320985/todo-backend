"""
TEST-05: error handling (section 4 of the team plan).

One parametrized test walks the table of every error the API answers and
checks, for each row, the single error format (ERR-02), that no English text
reaches the user, the security headers and the X-Request-ID (ERR-01, ERR-04)
and the row's own headers: WWW-Authenticate on 401, Retry-After on 429
(ERR-03) and on 503.

The exact 500/503 bodies and the logged traceback stay in
tests/test_error_handlers.py (ERR-01); /api/health/ready answering 503 with
the database unreachable is tests/test_health.py (ERR-05). Every test runs on
the TEST-01 database copied from the migrated template.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

import app.services.task_service as task_service
from app.core.logging import REQUEST_ID_HEADER
from app.core.rate_limit import RateLimiter
from conftest import TEST_EMAIL, TEST_PASSWORD, login
from helpers import create_task

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "cache-control": "no-store",
}

FORBIDDEN_ENGLISH = (
    "field required",
    "string should",
    "value error",
    "input should",
    "not found",
    "method not allowed",
    "not authenticated",
    "unauthorized",
    "too many requests",
    "internal server error",
    "service unavailable",
    "is not a valid",
    "at least",
    "at most",
    "too short",
    "too long",
)

RATE_LIMIT_WINDOW = 60
SECRET = "secreto-interno-no-debe-filtrarse"


@dataclass(frozen=True)
class Ctx:
    """What a row needs to provoke its error."""

    client: httpx.AsyncClient
    headers: dict[str, str]
    app: FastAPI
    monkeypatch: pytest.MonkeyPatch


RequestFactory = Callable[[Ctx], Awaitable[httpx.Response]]


async def _missing(ctx: Ctx) -> httpx.Response:
    return await ctx.client.post("/api/v1/tasks/", json={}, headers=ctx.headers)


async def _string_too_short(ctx: Ctx) -> httpx.Response:
    return await ctx.client.post(
        "/api/v1/tasks/", json={"title": ""}, headers=ctx.headers
    )


async def _string_too_long(ctx: Ctx) -> httpx.Response:
    return await ctx.client.post(
        "/api/v1/tasks/", json={"title": "x" * 201}, headers=ctx.headers
    )


async def _value_error(ctx: Ctx) -> httpx.Response:
    return await ctx.client.post(
        "/api/v1/auth/register",
        json={"email": "strength@example.com", "password": "onlyletters"},
    )


async def _json_invalid(ctx: Ctx) -> httpx.Response:
    return await ctx.client.post(
        "/api/v1/tasks/",
        content=b"{",
        headers={**ctx.headers, "Content-Type": "application/json"},
    )


async def _email_invalid(ctx: Ctx) -> httpx.Response:
    return await ctx.client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": TEST_PASSWORD},
    )


async def _not_found(ctx: Ctx) -> httpx.Response:
    return await ctx.client.get("/api/v1/no-existe")


async def _task_not_found(ctx: Ctx) -> httpx.Response:
    return await ctx.client.delete(
        "/api/v1/tasks/00000000-0000-0000-0000-000000000000", headers=ctx.headers
    )


async def _method_not_allowed(ctx: Ctx) -> httpx.Response:
    return await ctx.client.request("TRACE", "/api/health")


async def _not_authenticated(ctx: Ctx) -> httpx.Response:
    ctx.client.cookies.clear()
    return await ctx.client.get("/api/v1/tasks/")


async def _invalid_credentials(ctx: Ctx) -> httpx.Response:
    return await login(ctx.client, TEST_EMAIL, "wrongpassword1")


async def _date_range(ctx: Ctx) -> httpx.Response:
    task = await create_task(
        ctx.client, ctx.headers, title="Dated", start_date="2026-11-10"
    )
    return await ctx.client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"end_date": "2026-11-01"},
        headers=ctx.headers,
    )


async def _seg_h05(ctx: Ctx) -> httpx.Response:
    return await ctx.client.post(
        "/api/v1/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )


async def _seg_h06(ctx: Ctx) -> httpx.Response:
    return await ctx.client.patch(
        "/api/v1/tasks/not-a-uuid", json={"title": "x"}, headers=ctx.headers
    )


async def _task_limit(ctx: Ctx) -> httpx.Response:
    ctx.monkeypatch.setattr(task_service, "MAX_TASKS_PER_USER", 1)
    await create_task(ctx.client, ctx.headers, title="La única")
    return await ctx.client.post(
        "/api/v1/tasks/", json={"title": "Una más"}, headers=ctx.headers
    )


async def _rate_limited(ctx: Ctx) -> httpx.Response:
    # A frozen clock: the second attempt is blocked for the whole window.
    ctx.app.state.register_limiter = RateLimiter(
        max_attempts=1, window_seconds=RATE_LIMIT_WINDOW, clock=lambda: 1_000.0
    )
    body = {"email": "limit@example.com", "password": TEST_PASSWORD}
    assert (
        await ctx.client.post("/api/v1/auth/register", json=body)
    ).status_code == 201
    return await ctx.client.post("/api/v1/auth/register", json=body)


async def _internal_error(ctx: Ctx) -> httpx.Response:
    async def explode() -> None:
        raise RuntimeError(SECRET)

    ctx.app.add_api_route("/api/test/boom", explode, methods=["GET"])
    return await ctx.client.get("/api/test/boom")


async def _database_down(ctx: Ctx) -> httpx.Response:
    async def db_down() -> None:
        raise OperationalError("SELECT 1", {}, Exception(SECRET))

    ctx.app.add_api_route("/api/test/db-down", db_down, methods=["GET"])
    return await ctx.client.get("/api/test/db-down")


@pytest.mark.parametrize(
    (
        "make_request",
        "expected_status",
        "expected_code",
        "expected_detail",
        "expected_errors",
        "expected_headers",
    ),
    [
        pytest.param(
            _missing,
            422,
            "validation_error",
            "El título es obligatorio",
            (("title", "El título es obligatorio"),),
            {},
            id="missing",
        ),
        pytest.param(
            _string_too_short,
            422,
            "validation_error",
            "El título debe tener al menos 1 carácter",
            (("title", "debe tener al menos 1 carácter"),),
            {},
            id="string_too_short",
        ),
        pytest.param(
            _string_too_long,
            422,
            "validation_error",
            "El título no puede superar 200 caracteres",
            (("title", "no puede superar 200 caracteres"),),
            {},
            id="string_too_long",
        ),
        pytest.param(
            _value_error,
            422,
            "validation_error",
            "La contraseña debe incluir al menos una letra y un número",
            (("password", "debe incluir al menos una letra"),),
            {},
            id="value_error",
        ),
        pytest.param(
            _json_invalid,
            422,
            "validation_error",
            "El cuerpo de la petición no es un JSON válido",
            (("body", "no es un JSON válido"),),
            {},
            id="json_invalid",
        ),
        pytest.param(
            _email_invalid,
            422,
            "validation_error",
            "El email no es válido",
            (("email", "no es válido"),),
            {},
            id="email_invalid",
        ),
        pytest.param(
            _not_found,
            404,
            "not_found",
            "Recurso no encontrado",
            None,
            {},
            id="not_found",
        ),
        pytest.param(
            _task_not_found,
            404,
            "not_found",
            "Tarea no encontrada",
            None,
            {},
            id="task_not_found",
        ),
        pytest.param(
            _method_not_allowed,
            405,
            "method_not_allowed",
            "Método no permitido",
            None,
            {},
            id="method_not_allowed",
        ),
        pytest.param(
            _not_authenticated,
            401,
            "not_authenticated",
            "No se pudieron validar las credenciales",
            None,
            {"WWW-Authenticate": "Bearer"},
            id="not_authenticated",
        ),
        pytest.param(
            _invalid_credentials,
            401,
            "invalid_credentials",
            "Credenciales incorrectas",
            None,
            {"WWW-Authenticate": "Bearer"},
            id="invalid_credentials",
        ),
        pytest.param(
            _date_range,
            422,
            "validation_error",
            "La fecha de término no puede ser anterior a la fecha de inicio",
            (("end_date", "no puede ser anterior a la fecha de inicio"),),
            {},
            id="date_range",
        ),
        pytest.param(
            _seg_h05,
            400,
            "email_already_registered",
            "El email ya está registrado",
            None,
            {},
            id="seg_h05_duplicate_email",
        ),
        pytest.param(
            _seg_h06,
            422,
            "validation_error",
            "El id de la tarea no es válido",
            (("task_id", "no es válido"),),
            {},
            id="seg_h06_task_id_bounds",
        ),
        pytest.param(
            _task_limit,
            409,
            "task_limit_reached",
            "Alcanzaste el máximo de tareas permitido",
            None,
            {},
            id="seg_h12_task_limit",
        ),
        pytest.param(
            _rate_limited,
            429,
            "rate_limit_exceeded",
            "Demasiados intentos",
            None,
            {"Retry-After": str(RATE_LIMIT_WINDOW)},
            id="err03_rate_limited",
        ),
        pytest.param(
            _internal_error,
            500,
            "internal_error",
            "Ocurrió un error inesperado. Intenta de nuevo.",
            None,
            {},
            id="err01_internal_error",
        ),
        pytest.param(
            _database_down,
            503,
            "service_unavailable",
            "El servicio no está disponible temporalmente. Intenta de nuevo.",
            None,
            {"Retry-After": "1"},
            id="err01_database_unavailable",
        ),
    ],
)
async def test_every_error_uses_the_single_spanish_format(
    app: FastAPI,
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    make_request: RequestFactory,
    expected_status: int,
    expected_code: str,
    expected_detail: str,
    expected_errors: tuple[tuple[str, str], ...] | None,
    expected_headers: dict[str, str],
) -> None:
    response = await make_request(Ctx(client, auth_headers, app, monkeypatch))

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    expected_keys = (
        {"detail", "code", "errors"} if expected_errors else {"detail", "code"}
    )
    assert set(body) == expected_keys
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["code"] == expected_code
    assert expected_detail in body["detail"]

    if expected_errors:
        assert len(body["errors"]) == len(expected_errors)
        for item, (expected_field, expected_message) in zip(
            body["errors"], expected_errors
        ):
            assert set(item) == {"field", "message"}
            assert item["field"] == expected_field
            assert expected_message in item["message"]

    for name, value in {**SECURITY_HEADERS, **expected_headers}.items():
        assert response.headers.get(name) == value, (name, dict(response.headers))
    assert response.headers.get(REQUEST_ID_HEADER)

    assert SECRET not in response.text
    visible_text = " ".join(
        [body["detail"]] + [item["message"] for item in body.get("errors", [])]
    ).lower()
    for phrase in FORBIDDEN_ENGLISH:
        assert phrase not in visible_text
