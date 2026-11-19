"""Tests for the X-Request-ID middleware and the logging setup (ERR-04)."""

import logging
import re

import httpx
import pytest
from fastapi import FastAPI

from app.api.deps import get_current_user
from app.core.logging import REQUEST_ID_HEADER

# A generated id is 32 hex characters (uuid4 without dashes).
GENERATED_ID = re.compile(r"[0-9a-f]{32}")


async def test_response_carries_a_generated_request_id(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert GENERATED_ID.fullmatch(response.headers[REQUEST_ID_HEADER])


async def test_incoming_request_id_is_reused(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/health", headers={REQUEST_ID_HEADER: "nginx-abc123"}
    )

    assert response.headers[REQUEST_ID_HEADER] == "nginx-abc123"


@pytest.mark.parametrize(
    "hostile_id",
    [
        "bad\r\nX-Injected: 1",  # header injection
        "x" * 200,  # unbounded value
        "ruido con espacios",
        "",
    ],
)
async def test_invalid_request_id_is_replaced(
    client: httpx.AsyncClient, hostile_id: str
) -> None:
    response = await client.get(
        "/api/health", headers={REQUEST_ID_HEADER: hostile_id}
    )

    generated = response.headers[REQUEST_ID_HEADER]
    assert generated != hostile_id
    assert GENERATED_ID.fullmatch(generated)


async def test_500_is_logged_with_the_request_id_returned_to_the_client(
    app: FastAPI,
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The criterion of ERR-04: find a provoked 500 in the log by its id."""

    async def explode() -> None:
        raise RuntimeError("fallo provocado")

    app.dependency_overrides[get_current_user] = explode
    sent_id = "trace-500"

    response = await client.get(
        "/api/v1/tasks/", headers={REQUEST_ID_HEADER: sent_id}
    )

    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == sent_id

    records = [
        record
        for record in caplog.records
        if record.name == "app.request" and record.levelno >= logging.ERROR
    ]
    assert records, caplog.text
    assert getattr(records[0], "request_id") == sent_id
    # The traceback is part of the record, so the cause is visible in the log.
    assert "fallo provocado" in caplog.text


async def test_log_lines_include_date_level_logger_and_request_id(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    await client.get("/api/health", headers={REQUEST_ID_HEADER: "log-format"})

    handler = logging.getLogger().handlers[0]
    assert handler.formatter is not None
    fmt = handler.formatter._fmt or ""
    for field in ("%(asctime)s", "%(levelname)s", "%(name)s", "%(message)s"):
        assert field in fmt


def test_all_records_get_the_request_id_field() -> None:
    from app.core.logging import RequestIdFilter

    record = logging.LogRecord(
        name="auth", level=logging.WARNING, pathname="", lineno=1,
        msg="algo", args=(), exc_info=None,
    )
    assert RequestIdFilter().filter(record) is True
    assert record.request_id == "-"  # outside a request
