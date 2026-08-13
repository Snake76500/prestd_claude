import base64

import httpx
import pytest
import respx

from prestd_client import PrestdAuthError, PrestdClient
from prestd_client.auth import BasicAuth, CallableAuth, JWTAuth, StaticTokenAuth

BASE_URL = "http://testserver"


@pytest.mark.asyncio
async def test_static_token_auth_sets_bearer_header():
    client = PrestdClient(BASE_URL, default_database="mydb", auth=StaticTokenAuth("fixed-token"))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get("/mydb/public/users").mock(return_value=httpx.Response(200, json=[]))
        await client.table("users").execute()
    assert route.calls.last.request.headers["Authorization"] == "Bearer fixed-token"
    await client.close()


@pytest.mark.asyncio
async def test_basic_auth_header_format():
    client = PrestdClient(BASE_URL, default_database="mydb", auth=BasicAuth("prest", "prest"))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get("/mydb/public/users").mock(return_value=httpx.Response(200, json=[]))
        await client.table("users").execute()
    expected = "Basic " + base64.b64encode(b"prest:prest").decode()
    assert route.calls.last.request.headers["Authorization"] == expected
    await client.close()


@pytest.mark.asyncio
async def test_callable_auth_supports_sync_function():
    client = PrestdClient(BASE_URL, default_database="mydb", auth=CallableAuth(lambda: {"X-Api-Key": "k1"}))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get("/mydb/public/users").mock(return_value=httpx.Response(200, json=[]))
        await client.table("users").execute()
    assert route.calls.last.request.headers["X-Api-Key"] == "k1"
    await client.close()


@pytest.mark.asyncio
async def test_callable_auth_supports_async_function():
    async def get_headers():
        return {"X-Api-Key": "k2"}

    client = PrestdClient(BASE_URL, default_database="mydb", auth=CallableAuth(get_headers))
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get("/mydb/public/users").mock(return_value=httpx.Response(200, json=[]))
        await client.table("users").execute()
    assert route.calls.last.request.headers["X-Api-Key"] == "k2"
    await client.close()


@pytest.mark.asyncio
async def test_jwt_auth_logs_in_lazily_on_first_request():
    client = PrestdClient(BASE_URL, default_database="mydb", auth=JWTAuth("prest", "prest"))
    with respx.mock(base_url=BASE_URL) as mock:
        auth_route = mock.post("/auth").mock(return_value=httpx.Response(200, json={"token": "tok-1"}))
        get_route = mock.get("/mydb/public/users").mock(return_value=httpx.Response(200, json=[]))
        await client.table("users").execute()
        # deuxième appel : pas de nouveau /auth, le token est mis en cache
        await client.table("users").execute()
    assert auth_route.call_count == 1
    assert get_route.calls.last.request.headers["Authorization"] == "Bearer tok-1"
    await client.close()


@pytest.mark.asyncio
async def test_jwt_auth_relogs_in_once_on_401_and_retries():
    client = PrestdClient(BASE_URL, default_database="mydb", auth=JWTAuth("prest", "prest"))
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/auth").mock(
            side_effect=[
                httpx.Response(200, json={"token": "expired-token"}),
                httpx.Response(200, json={"token": "fresh-token"}),
            ]
        )
        get_route = mock.get("/mydb/public/users").mock(
            side_effect=[
                httpx.Response(401, json={"error": "token expired"}),
                httpx.Response(200, json=[{"id": 1}]),
            ]
        )
        rows = await client.table("users").execute()
    assert rows == [{"id": 1}]
    assert get_route.call_count == 2
    assert get_route.calls.last.request.headers["Authorization"] == "Bearer fresh-token"
    await client.close()


@pytest.mark.asyncio
async def test_jwt_auth_used_unbound_raises_prestd_auth_error():
    auth = JWTAuth("prest", "prest")
    with pytest.raises(PrestdAuthError):
        await auth.get_headers()


@pytest.mark.asyncio
async def test_explicit_set_token_overrides_auth_middleware():
    client = PrestdClient(BASE_URL, default_database="mydb", auth=StaticTokenAuth("from-middleware"))
    client.set_token("from-set-token")
    with respx.mock(base_url=BASE_URL) as mock:
        route = mock.get("/mydb/public/users").mock(return_value=httpx.Response(200, json=[]))
        await client.table("users").execute()
    assert route.calls.last.request.headers["Authorization"] == "Bearer from-set-token"
    await client.close()
