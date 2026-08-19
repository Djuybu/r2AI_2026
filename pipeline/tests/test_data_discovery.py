"""Unit tests for Data Registry and Discovery node."""

import unittest
from pathlib import Path
from pipeline.src.utils.data_registry import DataRegistry, get_table_schema
from pipeline.src.nodes.data_discovery import data_discovery_node
from pipeline.src.state import AgentState


class TestDataDiscovery(unittest.TestCase):

    def setUp(self):
        self.sample_csv = Path(__file__).resolve().parent.parent / "data" / "sample_sales.csv"

    def test_registry_scan(self):
        registry = DataRegistry()
        files = registry.scan_files()
        self.assertIn("sample_sales", files)

    def test_fuzzy_match(self):
        registry = DataRegistry()
        match = registry.find_best_match("sales")
        self.assertIsNotNone(match)
        self.assertEqual(match.name, "sample_sales.csv")

    def test_table_schema_extraction(self):
        schema = get_table_schema(self.sample_csv)
        self.assertEqual(schema["file_name"], "sample_sales.csv")
        self.assertIn("revenue", schema["columns"])
        self.assertGreater(len(schema["sample_rows"]), 0)

    def test_data_discovery_node_success(self):
        state: AgentState = {
            "user_query": "Doanh thu năm 2024",
            "parsed_query": {
                "ten_cong_ty": "FPT",
                "so_nam": ["2024"],
                "noi_dung": "sample_sales",
                "thao_tac": "trich_xuat"
            },
        }
        result = data_discovery_node(state)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(len(result.get("discovered_tables", [])) > 0 or result.get("matched_table_path") is not None)
        self.assertIn("data_discovery", result["node_latencies"])


if __name__ == "__main__":
    unittest.main()
