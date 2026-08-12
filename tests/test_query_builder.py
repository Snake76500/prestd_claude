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
