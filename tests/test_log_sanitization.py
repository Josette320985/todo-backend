import httpx
import pytest

from app.core.logging import sanitize_for_log
from conftest import login


@pytest.mark.parametrize(
    "raw",
    ["a\r\nFAKE LOG LINE", "\x1b[31mred", "a b", "a\x00b", "a\x7fb"],
)
def test_control_chars_are_escaped(raw: str) -> None:
    cleaned = sanitize_for_log(raw)
    assert cleaned.isprintable()
    assert cleaned.isascii()


def test_output_is_truncated() -> None:
    assert len(sanitize_for_log("x" * 500)) == 120


async def test_failed_login_logs_escaped_email(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    await login(client, email="\x1b[31mevil@example.com", password="wrong1234")
    assert "\x1b" not in caplog.text
    assert "\\x1b[31mevil@example.com" in caplog.text
