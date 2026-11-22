"""Tests for the global exception handlers (ERR-01)."""

import logging
import re

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from app.core.logging import REQUEST_ID_HEADER

EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "cache-control": "no-store",
}
GENERATED_ID = re.compile(r"[0-9a-f]{32}")


def assert_security_headers(response: httpx.Response) -> None:
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value, (name, dict(response.headers))


async def test_unhandled_exception_returns_spanish_500(
    app: FastAPI,
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def explode() -> None:
        raise RuntimeError("secreto-interno-no-debe-filtrarse")

    app.add_api_route("/api/test/boom", explode, methods=["GET"])
    sent_id = "trace-err01"

    with caplog.at_level(logging.ERROR):
        response = await client.get(
            "/api/test/boom", headers={REQUEST_ID_HEADER: sent_id}
        )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Ocurrió un error inesperado. Intenta de nuevo.",
        "code": "internal_error",
    }
    assert "secreto-interno-no-debe-filtrarse" not in response.text
    assert response.headers[REQUEST_ID_HEADER] == sent_id
    assert_security_headers(response)

    records = [
        record
        for record in caplog.records
        if record.name == "app.request" and record.levelno >= logging.ERROR
    ]
    assert records, caplog.text
    assert getattr(records[0], "request_id") == sent_id
    assert "GET /api/test/boom" in caplog.text
    assert "secreto-interno-no-debe-filtrarse" in caplog.text


async def test_operational_error_returns_503_with_retry_after(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    async def db_down() -> None:
        raise OperationalError("SELECT 1", {}, Exception("database secreta"))

    app.add_api_route("/api/test/db-down", db_down, methods=["GET"])

    response = await client.get("/api/test/db-down")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "El servicio no está disponible temporalmente. Intenta de nuevo.",
        "code": "service_unavailable",
    }
    assert response.headers["Retry-After"] == "1"
    assert "database secreta" not in response.text
    assert GENERATED_ID.fullmatch(response.headers[REQUEST_ID_HEADER])
    assert_security_headers(response)


async def test_invalid_request_id_is_replaced_and_logged(
    app: FastAPI,
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def explode() -> None:
        raise RuntimeError("fallo provocado")

    app.add_api_route("/api/test/boom-invalid-id", explode, methods=["GET"])

    with caplog.at_level(logging.ERROR):
        response = await client.get(
            "/api/test/boom-invalid-id",
            headers={REQUEST_ID_HEADER: "id con espacios"},
        )

    records = [
        record
        for record in caplog.records
        if record.name == "app.request" and record.levelno >= logging.ERROR
    ]
    assert records, caplog.text
    logged_id = getattr(records[0], "request_id")
    assert GENERATED_ID.fullmatch(logged_id)
    assert response.headers[REQUEST_ID_HEADER] == logged_id
    assert response.headers[REQUEST_ID_HEADER] != "id con espacios"
