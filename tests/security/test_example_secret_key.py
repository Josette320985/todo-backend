"""
SEG-01: a token forged with the published example SECRET_KEY is rejected.

The validator side (Settings rejects the example key) is covered in
tests/test_config.py. This test covers the attack from the report: an
attacker signs {"sub": "1"} with the text from the old .env.example.
"""

from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt

EXAMPLE_KEY = (
    "reemplaza-esta-clave-por-una-larga-y-aleatoria-de-al-menos-32-caracteres"
)


async def test_token_signed_with_example_key_is_401(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    now = datetime.now(timezone.utc)
    forged = jwt.encode(
        {"sub": "1", "ver": 0, "iat": now, "exp": now + timedelta(minutes=5)},
        EXAMPLE_KEY,
        algorithm="HS256",
    )

    response = await client.get(
        "/api/v1/tasks/", headers={"Authorization": f"Bearer {forged}"}
    )

    assert response.status_code == 401
