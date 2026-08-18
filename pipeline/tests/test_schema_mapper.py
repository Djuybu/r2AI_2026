"""Unit tests for Schema Mapper Node."""

import unittest
from pipeline.src.nodes.schema_mapper import _find_label_column, _find_value_column


class TestSchemaMapper(unittest.TestCase):

    def test_find_label_column(self):
        cols = ["Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "CHỈ TIÊU", "Năm nay", "Năm trước"]
        label_col = _find_label_column(cols)
        self.assertEqual(label_col, "CHỈ TIÊU")

    def test_find_value_column(self):
        cols = ["Ma_Doanh_Nghiep", "CHỈ TIÊU", "Mã số", "Năm nay", "Năm trước"]
        val_col = _find_value_column(cols, label_col="CHỈ TIÊU", tieu_chi_phu="Năm nay")
        self.assertEqual(val_col, "Năm nay")


if __name__ == "__main__":
    unittest.main()

