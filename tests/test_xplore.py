from ieee_spider.models import SearchQuery
from ieee_spider.xplore import author_matches, build_query_text


def test_build_xplore_query_combines_generic_fields() -> None:
    query = SearchQuery(
        query="low altitude networks",
        title="coverage",
        author="Example Author",
        venue="IEEE Transactions on Wireless Communications",
    )

    assert build_query_text(query) == (
        "(low altitude networks) AND "
        '"Document Title":"coverage" AND '
        '"Authors":"Example Author" AND '
        '"Publication Title":"IEEE Transactions on Wireless Communications"'
    )


def test_build_xplore_query_applies_year_range() -> None:
    query = SearchQuery(
        query="wireless networks",
        from_year=2025,
        to_year=2026,
    )

    assert build_query_text(query) == (
        '(wireless networks) AND ("Publication Year":2025 OR '
        '"Publication Year":2026)'
    )


def test_author_match_is_case_and_whitespace_insensitive() -> None:
    assert author_matches(
        "Example Author",
        ["Example  Author", "Someone Else"],
    )


def test_author_match_rejects_same_surname_or_substring() -> None:
    assert not author_matches(
        "Example Author",
        ["Author Example", "Example Author Jr"],
    )
