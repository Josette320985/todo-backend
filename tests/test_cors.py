import httpx

ALLOWED_ORIGIN = "http://localhost:3000"


async def _preflight(client: httpx.AsyncClient, origin: str) -> httpx.Response:
    return await client.options(
        "/api/v1/tasks/",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


async def test_allowed_origin_with_credentials(client: httpx.AsyncClient) -> None:
    response = await _preflight(client, ALLOWED_ORIGIN)
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


async def test_unknown_origin_is_rejected(client: httpx.AsyncClient) -> None:
    response = await _preflight(client, "http://evil.example")
    assert "access-control-allow-origin" not in response.headers


async def test_patch_preflight_is_allowed(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/api/v1/tasks/1",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "PATCH",
        },
    )

    assert "PATCH" in response.headers["access-control-allow-methods"]
