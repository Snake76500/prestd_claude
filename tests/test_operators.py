from prestd_client.operators import Agg, Op


def test_eq_is_bare_value():
    assert Op.eq("active") == "active"
    assert Op.eq(42) == "42"


def test_comparison_operators():
    assert Op.gt(25) == "$gt.25"
    assert Op.gte(25) == "$gte.25"
    assert Op.lt(5) == "$lt.5"
    assert Op.lte(4.5) == "$lte.4.5"
    assert Op.ne("closed") == "$ne.closed"


def test_in_and_nin_join_with_comma():
    assert Op.in_(["admin", "editor", "viewer"]) == "$in.admin,editor,viewer"
    assert Op.nin(["hr", "finance"]) == "$nin.hr,finance"


def test_null_and_boolean_helpers():
    assert Op.is_null() == "$null"
    assert Op.is_not_null() == "$notnull"
    assert Op.is_true() == "$true"
    assert Op.is_not_true() == "$nottrue"
    assert Op.is_false() == "$false"
    assert Op.is_not_false() == "$notfalse"


def test_like_family():
    assert Op.like("John%") == "$like.John%"
    assert Op.ilike("mumbai%") == "$ilike.mumbai%"
    assert Op.nlike("%@test.com") == "$nlike.%@test.com"
    assert Op.nilike("%@gmail.com") == "$nilike.%@gmail.com"


def test_ltree_helpers():
    assert Op.ltree_ancestor("electronics") == "$ltreelanc.electronics"
    assert Op.ltree_descendant("electronics.mobiles") == "$ltreerdesc.electronics.mobiles"


def test_aggregate_helpers():
    assert Agg.sum("salary") == "sum:salary"
    assert Agg.avg("rating") == "avg:rating"
    assert Agg.max("age") == "max:age"
    assert Agg.min("age") == "min:age"
    assert Agg.stddev("score") == "stddev:score"
    assert Agg.variance("score") == "variance:score"
