import httpx
import pytest
import respx

from prestd_client import (
    PrestdAuthError,
    PrestdClient,
    PrestdNotFoundError,
    PrestdValidationError,
)

BASE_URL = "http://testserver"


@pytest.fixture
def client():
    c = PrestdClient(BASE_URL, default_database="mydb", default_schema="public")
    yield c


@pytest.mark.asyncio
async def test_select_rows(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/mydb/public/users", params={"active": "True"}).mock(
            return_value=httpx.Response(200, json=[{"id": 1, "name": "Ragnar"}])
        )
        rows = await client.table("users").eq("active", True).execute()
    assert rows == [{"id": 1, "name": "Ragnar"}]
    await client.close()


@pytest.mark.asyncio
async def test_insert_row(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/mydb/public/users").mock(
            return_value=httpx.Response(201, json={"id": 2, "name": "Fabien"})
        )
        result = await client.insert("users", {"name": "Fabien"})
    assert result == {"id": 2, "name": "Fabien"}
    await client.close()


@pytest.mark.asyncio
async def test_update_requires_filters(client):
    with pytest.raises(ValueError):
        await client.update("users", {"active": False}, {})
    await client.close()


@pytest.mark.asyncio
async def test_delete_requires_filters(client):
    with pytest.raises(ValueError):
        await client.delete("users", {})
    await client.close()


@pytest.mark.asyncio
async def test_update_with_filters(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.patch("/mydb/public/users", params={"id": "42"}).mock(
            return_value=httpx.Response(200, json={"id": 42, "active": False})
        )
        result = await client.update("users", {"active": False}, {"id": "42"})
    assert result == {"id": 42, "active": False}
    await client.close()


@pytest.mark.asyncio
async def test_404_maps_to_not_found_error(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/mydb/public/ghost_table").mock(
            return_value=httpx.Response(404, json={"error": "relation does not exist"})
        )
        with pytest.raises(PrestdNotFoundError):
            await client.table("ghost_table").execute()
    await client.close()


@pytest.mark.asyncio
async def test_400_maps_to_validation_error(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/mydb/public/users").mock(
            return_value=httpx.Response(400, json={"error": "invalid filter"})
        )
        with pytest.raises(PrestdValidationError):
            await client.table("users").execute()
    await client.close()


@pytest.mark.asyncio
async def test_login_sets_token_and_is_sent_on_next_call(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/auth").mock(return_value=httpx.Response(200, json={"token": "abc123"}))
        get_route = mock.get("/mydb/public/users").mock(return_value=httpx.Response(200, json=[]))

        token = await client.login("prest", "prest")
        assert token == "abc123"

        await client.table("users").execute()
        sent_request = get_route.calls.last.request
        assert sent_request.headers["Authorization"] == "Bearer abc123"
    await client.close()


@pytest.mark.asyncio
async def test_login_without_token_raises_auth_error(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.post("/auth").mock(return_value=httpx.Response(200, json={"unexpected": "shape"}))
        with pytest.raises(PrestdAuthError):
            await client.login("prest", "wrong")
    await client.close()


@pytest.mark.asyncio
async def test_no_default_database_raises_value_error():
    c = PrestdClient(BASE_URL)
    with pytest.raises(ValueError):
        c.table("users")
    await c.close()


@pytest.mark.asyncio
async def test_describe_table_with_datasource(client):
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/show/other_ds/public/products").mock(
            return_value=httpx.Response(200, json=[{"column_name": "id"}])
        )
        cols = await client.describe_table("products", datasource="other_ds")
    assert cols == [{"column_name": "id"}]
    await client.close()


def test_sync_client_describe_table():
    from prestd_client.sync_client import SyncPrestdClient

    sync_c = SyncPrestdClient(BASE_URL, default_database="mydb", default_schema="public")
    with respx.mock(base_url=BASE_URL) as mock:
        mock.get("/show/ds1/custom_sch/items").mock(
            return_value=httpx.Response(200, json=[{"column_name": "sku"}])
        )
        cols = sync_c.describe_table("items", datasource="ds1", schema="custom_sch")
    assert cols == [{"column_name": "sku"}]
    sync_c.close()


def test_sync_client_full_flow():
    from prestd_client.sync_client import SyncPrestdClient

    with SyncPrestdClient(BASE_URL, default_database="mydb", default_schema="public") as sync_c:
        with respx.mock(base_url=BASE_URL) as mock:
            mock.get("/_health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
            mock.get("/_ready").mock(return_value=httpx.Response(200, json={"status": "ok"}))
            mock.get("/databases").mock(return_value=httpx.Response(200, json=[{"datname": "mydb"}]))
            mock.get("/schemas").mock(return_value=httpx.Response(200, json=[{"schema_name": "public"}]))
            mock.get("/tables").mock(return_value=httpx.Response(200, json=[{"table_name": "users"}]))
            mock.post("/mydb/public/users").mock(return_value=httpx.Response(201, json=[{"id": 1}, {"id": 2}]))
            mock.delete("/mydb/public/users", params={"id": "1"}).mock(return_value=httpx.Response(200, json={"deleted": 1}))

            assert sync_c.health() == {"status": "ok"}
            assert sync_c.ready() == {"status": "ok"}
            assert sync_c.databases() == [{"datname": "mydb"}]
            assert sync_c.schemas() == [{"schema_name": "public"}]
            assert sync_c.tables() == [{"table_name": "users"}]
            assert sync_c.batch_insert("users", [{"name": "A"}, {"name": "B"}]) == [{"id": 1}, {"id": 2}]
            assert sync_c.delete("users", {"id": "1"}) == {"deleted": 1}


