"""Unit tests for Query Parser node and utilities."""

import unittest
from unittest.mock import MagicMock, patch
from pipeline.src.utils.json_repair import safe_parse_json
from pipeline.src.nodes.query_parser import parse_query_node, _fallback_parse_query
from pipeline.src.state import AgentState


class TestQueryParser(unittest.TestCase):

    def test_json_repair_valid_json(self):
        raw = '{"ten_cong_ty": "Vinamilk", "noi_dung": "Doanh thu"}'
        parsed = safe_parse_json(raw)
        self.assertEqual(parsed["ten_cong_ty"], "Vinamilk")
        self.assertEqual(parsed["noi_dung"], "Doanh thu")

    def test_json_repair_codeblock_markdown(self):
        raw = '```json\n{"ten_cong_ty": "FPT", "thao_tac": "so_sanh"}\n```'
        parsed = safe_parse_json(raw)
        self.assertEqual(parsed["ten_cong_ty"], "FPT")
        self.assertEqual(parsed["thao_tac"], "so_sanh")

    def test_json_repair_malformed_json(self):
        raw = '{"ten_cong_ty": "VCB", "so_nam": ["2023"],}'
        parsed = safe_parse_json(raw)
        self.assertEqual(parsed.get("ten_cong_ty"), "VCB")

    @patch("pipeline.src.nodes.query_parser.get_llm")
    def test_parse_query_node_success(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value.content = '{"ten_cong_ty": "FPT", "so_nam": ["2024"], "noi_dung": "Doanh thu", "thao_tac": "trich_xuat", "tieu_chi_phu": null}'
        mock_get_llm.return_value = mock_llm

        state: AgentState = {"user_query": "Tính tổng doanh thu năm 2024 của FPT"}
        result = parse_query_node(state)

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["parsed_query"]["ten_cong_ty"], "FPT")
        self.assertEqual(result["parsed_query"]["thao_tac"], "trich_xuat")
        self.assertEqual(result["parsed_query"]["muc_tieu"], "trich_xuat")
        self.assertIn("query_parser", result["node_latencies"])

    def test_fallback_parse_query_range(self):
        query = "So sánh lợi nhuận sau thuế của VCB từ năm 2021 đến năm 2023"
        parsed = _fallback_parse_query(query)
        self.assertEqual(parsed["ten_cong_ty"], "VCB")
        self.assertEqual(parsed["so_nam"], ["2021", "2022", "2023"])
        self.assertEqual(parsed["thao_tac"], "so_sanh")

    def test_parse_query_node_empty_query(self):
        state: AgentState = {"user_query": ""}
        result = parse_query_node(state)

        self.assertEqual(result["status"], "error")
        self.assertIn("empty", result["error_message"].lower())


if __name__ == "__main__":
    unittest.main()
