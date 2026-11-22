"""ERR-02: single Spanish error format for every API error response."""

from collections.abc import Awaitable, Callable

import httpx
import pytest

from conftest import TEST_EMAIL, TEST_PASSWORD
from helpers import create_task

RequestFactory = Callable[
    [httpx.AsyncClient, dict[str, str]], Awaitable[httpx.Response]
]

FORBIDDEN_ENGLISH = (
    "field required",
    "string should",
    "value error",
    "input should",
    "not found",
    "method not allowed",
    "not authenticated",
    "is not a valid",
    "at least",
    "at most",
    "too short",
    "too long",
)


async def _missing(client: httpx.AsyncClient, headers: dict[str, str]) -> httpx.Response:
    return await client.post("/api/v1/tasks/", json={}, headers=headers)


async def _string_too_short(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> httpx.Response:
    return await client.post(
        "/api/v1/tasks/", json={"title": ""}, headers=headers
    )


async def _string_too_long(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> httpx.Response:
    return await client.post(
        "/api/v1/tasks/", json={"title": "x" * 201}, headers=headers
    )


async def _value_error(
    client: httpx.AsyncClient, _headers: dict[str, str]
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/register",
        json={"email": "strength@example.com", "password": "onlyletters"},
    )


async def _json_invalid(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> httpx.Response:
    return await client.post(
        "/api/v1/tasks/",
        content=b"{",
        headers={**headers, "Content-Type": "application/json"},
    )


async def _email_invalid(
    client: httpx.AsyncClient, _headers: dict[str, str]
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": TEST_PASSWORD},
    )


async def _not_found(
    client: httpx.AsyncClient, _headers: dict[str, str]
) -> httpx.Response:
    return await client.get("/api/v1/no-existe")


async def _method_not_allowed(
    client: httpx.AsyncClient, _headers: dict[str, str]
) -> httpx.Response:
    return await client.request("TRACE", "/api/health")


async def _not_authenticated(
    client: httpx.AsyncClient, _headers: dict[str, str]
) -> httpx.Response:
    return await client.get("/api/v1/tasks/")


async def _date_range(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> httpx.Response:
    task = await create_task(
        client, headers, title="Dated", start_date="2026-11-10"
    )
    return await client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"end_date": "2026-11-01"},
        headers=headers,
    )


async def _seg_h05(
    client: httpx.AsyncClient, _headers: dict[str, str]
) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/register",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
    )


async def _seg_h06(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> httpx.Response:
    return await client.patch(
        f"/api/v1/tasks/{2**63}", json={"title": "x"}, headers=headers
    )


@pytest.mark.parametrize(
    (
        "make_request",
        "expected_status",
        "expected_code",
        "expected_detail",
        "expected_errors",
        "expected_header",
    ),
    [
        pytest.param(
            _missing,
            422,
            "validation_error",
            "El título es obligatorio",
            (("title", "El título es obligatorio"),),
            None,
            id="missing",
        ),
        pytest.param(
            _string_too_short,
            422,
            "validation_error",
            "El título debe tener al menos 1 carácter",
            (("title", "debe tener al menos 1 carácter"),),
            None,
            id="string_too_short",
        ),
        pytest.param(
            _string_too_long,
            422,
            "validation_error",
            "El título no puede superar 200 caracteres",
            (("title", "no puede superar 200 caracteres"),),
            None,
            id="string_too_long",
        ),
        pytest.param(
            _value_error,
            422,
            "validation_error",
            "La contraseña debe incluir al menos una letra y un número",
            (("password", "debe incluir al menos una letra"),),
            None,
            id="value_error",
        ),
        pytest.param(
            _json_invalid,
            422,
            "validation_error",
            "El cuerpo de la petición no es un JSON válido",
            (("body", "no es un JSON válido"),),
            None,
            id="json_invalid",
        ),
        pytest.param(
            _email_invalid,
            422,
            "validation_error",
            "El email no es válido",
            (("email", "no es válido"),),
            None,
            id="email_invalid",
        ),
        pytest.param(
            _not_found,
            404,
            "not_found",
            "Recurso no encontrado",
            None,
            None,
            id="not_found",
        ),
        pytest.param(
            _method_not_allowed,
            405,
            "method_not_allowed",
            "Método no permitido",
            None,
            None,
            id="method_not_allowed",
        ),
        pytest.param(
            _not_authenticated,
            401,
            "not_authenticated",
            "No se pudieron validar las credenciales",
            None,
            ("WWW-Authenticate", "Bearer"),
            id="not_authenticated",
        ),
        pytest.param(
            _date_range,
            422,
            "validation_error",
            "La fecha de término no puede ser anterior a la fecha de inicio",
            (("end_date", "no puede ser anterior a la fecha de inicio"),),
            None,
            id="date_range",
        ),
        pytest.param(
            _seg_h05,
            400,
            "email_already_registered",
            "El email ya está registrado",
            None,
            None,
            id="seg_h05_duplicate_email",
        ),
        pytest.param(
            _seg_h06,
            422,
            "validation_error",
            "El id de la tarea debe ser menor o igual que",
            (("task_id", "debe ser menor o igual que"),),
            None,
            id="seg_h06_task_id_bounds",
        ),
    ],
)
async def test_every_error_uses_the_single_spanish_format(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    make_request: RequestFactory,
    expected_status: int,
    expected_code: str,
    expected_detail: str,
    expected_errors: tuple[tuple[str, str], ...] | None,
    expected_header: tuple[str, str] | None,
) -> None:
    response = await make_request(client, auth_headers)

    assert response.status_code == expected_status
    body = response.json()
    expected_keys = (
        {"detail", "code", "errors"} if expected_errors else {"detail", "code"}
    )
    assert set(body) == expected_keys
    assert isinstance(body["detail"], str) and body["detail"]
    assert isinstance(body["code"], str)
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

    if expected_header:
        name, value = expected_header
        assert response.headers.get(name) == value

    visible_text = " ".join(
        [body["detail"]]
        + [item["message"] for item in body.get("errors", [])]
    ).lower()
    for phrase in FORBIDDEN_ENGLISH:
        assert phrase not in visible_text
