import httpx

from conftest import login


async def test_logout_revokes_previous_token(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post("/api/v1/auth/logout", headers=auth_headers)
    assert response.status_code == 204

    response = await client.get("/api/v1/tasks/", headers=auth_headers)
    assert response.status_code == 401


async def test_new_login_works_after_logout(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await client.post("/api/v1/auth/logout", headers=auth_headers)

    token = (await login(client)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.get("/api/v1/tasks/", headers=headers)
    assert response.status_code == 200


async def test_logout_requires_token(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 401
