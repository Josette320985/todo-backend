import httpx


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_authenticated_request(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/tasks/", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_missing_token_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/tasks/")
    assert response.status_code == 401
