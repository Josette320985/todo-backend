"""
TEST-04: unit tests of the request schemas (no app, no database).

- TaskCreate: every date combination (only start, only end, both).
- TaskUpdate: an explicit null in title or completed is rejected.
- UserCreate: 8 characters minimum, a letter and a digit, and the 72-byte
  bcrypt limit counted in UTF-8 bytes, not characters.

Partial updates against the stored dates are in
tests/services/test_task_dates.py; the RateLimiter with a fake clock is in
tests/test_arq05_rate_limit.py.
"""

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.dates import DATE_RANGE_ERROR
from app.schemas.task import TaskCreate, TaskUpdate
from app.schemas.user import UserCreate

EARLY = date(2026, 11, 1)
LATE = date(2026, 11, 10)
EMAIL = "user@example.com"


def error_messages(exc: pytest.ExceptionInfo[ValidationError]) -> str:
    return " | ".join(str(error["msg"]) for error in exc.value.errors())


# --- TaskCreate: date range ---------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end"),
    [
        pytest.param(None, None, id="no-dates"),
        pytest.param(EARLY, None, id="only-start"),
        pytest.param(None, LATE, id="only-end"),
        pytest.param(EARLY, LATE, id="both"),
        pytest.param(EARLY, EARLY, id="same-day"),
    ],
)
def test_task_create_accepts_valid_ranges(
    start: date | None, end: date | None
) -> None:
    task = TaskCreate(title="t", start_date=start, end_date=end)

    assert (task.start_date, task.end_date) == (start, end)


def test_task_create_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError) as exc:
        TaskCreate(title="t", start_date=LATE, end_date=EARLY)

    assert DATE_RANGE_ERROR in error_messages(exc)


def test_task_update_rejects_end_before_start_in_the_same_request() -> None:
    with pytest.raises(ValidationError) as exc:
        TaskUpdate(start_date=LATE, end_date=EARLY)

    assert DATE_RANGE_ERROR in error_messages(exc)


# --- TaskUpdate: explicit null ------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        pytest.param({"title": None}, "El título no puede ser nulo", id="title"),
        pytest.param(
            {"completed": None},
            "El estado 'completed' no puede ser nulo",
            id="completed",
        ),
    ],
)
def test_task_update_rejects_explicit_null(
    payload: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError) as exc:
        TaskUpdate.model_validate(payload)

    assert message in error_messages(exc)


def test_task_update_omitted_fields_are_not_null_updates() -> None:
    update = TaskUpdate.model_validate({})

    assert update.model_dump(exclude_unset=True) == {}


@pytest.mark.parametrize("field", ["description", "start_date", "end_date"])
def test_task_update_accepts_null_in_nullable_fields(field: str) -> None:
    update = TaskUpdate.model_validate({field: None})

    assert update.model_dump(exclude_unset=True) == {field: None}


# --- UserCreate: password -----------------------------------------------------


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("abcdef12", id="8-chars"),
        pytest.param("a" * 71 + "1", id="72-ascii-bytes"),
        # 35 x "ñ" (2 bytes each) + "a1" = 72 bytes in 37 characters.
        pytest.param("ñ" * 35 + "a1", id="72-bytes-multibyte"),
        # 64-char lowercase hex SHA-256 digest sent by the frontend.
        pytest.param("a" * 64, id="sha256-hex"),
    ],
)
def test_user_create_accepts_valid_passwords(password: str) -> None:
    assert UserCreate(email=EMAIL, password=password).password == password


@pytest.mark.parametrize(
    ("password", "message"),
    [
        pytest.param("abcde12", "at least 8 characters", id="7-chars"),
        pytest.param(
            "solamenteletras",
            "al menos una letra y un número",
            id="no-digit",
        ),
        pytest.param("12345678", "al menos una letra y un número", id="no-letter"),
        pytest.param(" " * 8, "únicamente espacios", id="only-spaces"),
        pytest.param("a" * 72 + "1", "at most 72 characters", id="73-chars"),
        # 37 characters, under the 72-character limit, but 74 bytes.
        pytest.param("ñ" * 37, "72 bytes", id="37-enie-74-bytes"),
        pytest.param("ñ" * 36 + "1", "72 bytes", id="73-bytes-multibyte"),
    ],
)
def test_user_create_rejects_invalid_passwords(password: str, message: str) -> None:
    with pytest.raises(ValidationError) as exc:
        UserCreate(email=EMAIL, password=password)

    # The raw Pydantic message: the API translates it to Spanish (ERR-02).
    assert message in error_messages(exc)
