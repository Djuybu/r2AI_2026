"""Unit tests for Vector Store CSV extraction."""

import unittest
import tempfile
import shutil
from unittest.mock import MagicMock, patch
import pytest

try:
    import chromadb
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False

from pipeline.src.utils.vector_store import VectorSchemaStore


@pytest.mark.skipif(not HAS_CHROMADB, reason="chromadb package is not installed")
class TestVectorSchemaStore(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.vector_store = VectorSchemaStore(persist_dir=self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("chromadb.PersistentClient")
    def test_extract_csv_files_mock(self, mock_chroma):
        mock_collection = MagicMock()
        mock_collection.count.return_value = 2
        mock_collection.query.return_value = {
            "metadatas": [[
                {"file_name": "sales.csv", "file_path": "/data/sales.csv"},
                {"file_name": "users.xlsx", "file_path": "/data/users.xlsx"},
            ]],
            "distances": [[0.1, 0.5]]
        }
        mock_chroma.return_value.get_or_create_collection.return_value = mock_collection

        results = self.vector_store.extract_csv_files("sales report", top_k=2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["file_name"], "sales.csv")


if __name__ == "__main__":
    unittest.main()
