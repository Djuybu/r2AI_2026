"""Unit tests for Schema Mapper Node."""

from pipeline.src.nodes.schema_mapper import fuzzy_match_columns


def test_fuzzy_match_columns():
    query_terms = ["revenue", "order date", "category"]
    actual_columns = ["Order_Date", "Total_Revenue", "Product_Category"]

    mapping = fuzzy_match_columns(query_terms, actual_columns, cutoff=50)
    assert len(mapping) > 0
    assert mapping["revenue"] == "Total_Revenue"
