import pytest
from prestd_client.query import QueryBuilder


def make_qb() -> QueryBuilder:
    # client=None : suffisant tant qu'on ne fait que construire les params,
    # sans appeler .execute().
    return QueryBuilder(None, "mydb", "public", "users")


def test_simple_eq_filter():
    qb = make_qb().eq("active", True)
    assert qb._build_params() == {"active": "True"}


def test_comparison_filters():
    qb = make_qb().gt("age", 25).lte("rating", 4.5)
    assert qb._build_params() == {"age": "$gt.25", "rating": "$lte.4.5"}


def test_in_filter():
    qb = make_qb().in_("role", ["admin", "editor"])
    assert qb._build_params()["role"] == "$in.admin,editor"


def test_select_order_page():
    qb = make_qb().select("id", "name").order("-created_at").page(2, 20)
    params = qb._build_params()
    assert params["_select"] == "id,name"
    assert params["_order"] == "-created_at"
    assert params["_page"] == "2"
    assert params["_page_size"] == "20"


def test_count_first_only():
    qb = make_qb().count("*", first_only=True)
    params = qb._build_params()
    assert params["_count"] == "*"
    assert params["_count_first"] == "true"


def test_or_conditions_joined_with_double_pipe():
    qb = make_qb().or_("title=$ilike.%foo%", "name=$ilike.%foo%").eq("category", "tech")
    params = qb._build_params()
    assert params["_or"] == "title=$ilike.%foo%||name=$ilike.%foo%"
    assert params["category"] == "tech"


def test_knn_order_formats_vector_as_bracketed_list():
    qb = make_qb().knn_order("embedding", "cosine", [0.1, 0.2, 0.3])
    assert qb._build_params()["_korder"] == "embedding:cosine:[0.1,0.2,0.3]"


def test_fluent_calls_return_same_builder():
    qb = make_qb()
    assert qb.eq("a", 1) is qb
    assert qb.select("a") is qb
    assert qb.order("a") is qb


@pytest.mark.asyncio
async def test_query_builder_write_operations():
    import respx
    import httpx
    from prestd_client import PrestdClient

    c = PrestdClient("http://testserver", default_database="mydb", default_schema="public")
    with respx.mock(base_url="http://testserver") as mock:
        mock.post("/mydb/public/users").mock(return_value=httpx.Response(201, json={"id": 1}))
        mock.patch("/mydb/public/users", params={"id": "42"}).mock(return_value=httpx.Response(200, json={"id": 42}))
        mock.delete("/mydb/public/users", params={"id": "42"}).mock(return_value=httpx.Response(200, json={"deleted": 1}))

        res_insert = await c.table("users").insert({"name": "Alice"})
        assert res_insert == {"id": 1}

        res_update = await c.table("users").eq("id", 42).update({"active": False})
        assert res_update == {"id": 42}

        res_delete = await c.table("users").eq("id", 42).delete()
        assert res_delete == {"deleted": 1}
    await c.close()


@pytest.mark.asyncio
async def test_query_builder_pagination_slicing():
    import respx
    import httpx
    from prestd_client import PrestdClient

    c = PrestdClient("http://testserver", default_database="mydb", default_schema="public")
    all_data = [{"id": i, "name": f"User{i}"} for i in range(1, 11)]

    with respx.mock(base_url="http://testserver") as mock:
        # Simule un prestd qui renvoie toutes les lignes sans paginer
        mock.get("/mydb/public/users", params={"_page": "2", "_page_size": "3"}).mock(
            return_value=httpx.Response(200, json=all_data)
        )
        mock.get("/mydb/public/users", params={"_page": "1", "_page_size": "3"}).mock(
            return_value=httpx.Response(200, json=all_data)
        )

        # Page 2 de taille 3 -> User4, User5, User6
        page2 = await c.table("users").page(2, page_size=3).execute()
        assert len(page2) == 3
        assert [u["id"] for u in page2] == [4, 5, 6]

        # Page 1 de taille 3 -> User1, User2, User3
        page1 = await c.table("users").page(1, page_size=3).execute()
        assert len(page1) == 3
        assert [u["id"] for u in page1] == [1, 2, 3]

    await c.close()


@pytest.mark.asyncio
async def test_query_builder_default_and_max_page_size():
    import respx
    import httpx
    from prestd_client import PrestdClient

    # Client avec page par défaut = 50 et max = 200
    c = PrestdClient(
        "http://testserver",
        default_database="mydb",
        default_schema="public",
        default_page_size=50,
        max_page_size=200,
    )

    with respx.mock(base_url="http://testserver") as mock:
        # 1. Sans .page() -> injecte _page=1 et _page_size=50
        route1 = mock.get("/mydb/public/users", params={"_page": "1", "_page_size": "50"}).mock(
            return_value=httpx.Response(200, json=[{"id": 1}])
        )
        res = await c.table("users").execute()
        assert res == [{"id": 1}]
        assert route1.called

        # 2. Avec .page(1, page_size=5000) -> plafonné à 200
        route2 = mock.get("/mydb/public/users", params={"_page": "1", "_page_size": "200"}).mock(
            return_value=httpx.Response(200, json=[{"id": 2}])
        )
        res2 = await c.table("users").page(1, 5000).execute()
        assert res2 == [{"id": 2}]
        assert route2.called

    await c.close()


@pytest.mark.asyncio
async def test_query_builder_streaming():
    import respx
    import httpx
    from prestd_client import PrestdClient

    c = PrestdClient("http://testserver", default_database="mydb", default_schema="public")

    with respx.mock(base_url="http://testserver") as mock:
        # Page 1: 3 éléments
        mock.get("/mydb/public/users", params={"_page": "1", "_page_size": "3"}).mock(
            return_value=httpx.Response(200, json=[{"id": 1}, {"id": 2}, {"id": 3}])
        )
        # Page 2: 2 éléments (< batch_size 3 -> fin de l'itération)
        mock.get("/mydb/public/users", params={"_page": "2", "_page_size": "3"}).mock(
            return_value=httpx.Response(200, json=[{"id": 4}, {"id": 5}])
        )

        # Test stream() un par un
        collected_ids = []
        async for row in c.table("users").stream(batch_size=3):
            collected_ids.append(row["id"])

        assert collected_ids == [1, 2, 3, 4, 5]

    await c.close()
