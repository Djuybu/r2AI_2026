"""Unit tests for Query Parser node and utilities."""

import unittest
from unittest.mock import MagicMock, patch
from pipeline.src.utils.json_repair import safe_parse_json
from pipeline.src.nodes.query_parser import parse_query_node
from pipeline.src.state import AgentState


class TestQueryParser(unittest.TestCase):

    def test_json_repair_valid_json(self):
        raw = '{"file_name": "sales", "intent": "aggregate"}'
        parsed = safe_parse_json(raw)
        self.assertEqual(parsed["file_name"], "sales")
        self.assertEqual(parsed["intent"], "aggregate")

    def test_json_repair_codeblock_markdown(self):
        raw = '```json\n{"file_name": "report", "intent": "filter_sort"}\n```'
        parsed = safe_parse_json(raw)
        self.assertEqual(parsed["file_name"], "report")
        self.assertEqual(parsed["intent"], "filter_sort")

    def test_json_repair_malformed_json(self):
        raw = '{"file_name": "data", "intent": "compare",}'
        parsed = safe_parse_json(raw)
        self.assertEqual(parsed.get("file_name"), "data")

    @patch("pipeline.src.nodes.query_parser.get_llm")
    def test_parse_query_node_success(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = '{"file_name": "sales_2024", "query_details": [{"column_name": "revenue", "operation": "sum"}], "intent": "aggregate"}'
        mock_get_llm.return_value = mock_llm

        state: AgentState = {"user_query": "Tính tổng doanh thu năm 2024 từ file sales_2024"}
        result = parse_query_node(state)

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["parsed_query"]["file_name"], "sales_2024")
        self.assertEqual(result["parsed_query"]["intent"], "aggregate")
        self.assertIn("query_parser", result["node_latencies"])

    def test_parse_query_node_empty_query(self):
        state: AgentState = {"user_query": ""}
        result = parse_query_node(state)

        self.assertEqual(result["status"], "error")
        self.assertIn("empty", result["error_message"].lower())


if __name__ == "__main__":
    unittest.main()
