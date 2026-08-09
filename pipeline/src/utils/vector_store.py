"""Vector DB module for querying and extracting CSV data file metadata on Kaggle."""

from pathlib import Path
from typing import Dict, List, Optional
from src.config import Config, config as default_config


class VectorSchemaStore:
    """Vector Database client to query and extract CSV file metadata."""

    def __init__(self, cfg: Optional[Config] = None, persist_dir: Optional[str] = None):
        self.cfg = cfg or default_config
        self.persist_dir = persist_dir or str(self.cfg.BASE_DIR / "vector_db")
        self._client = None
        self._collection = None

    def _init_chroma(self):
        """Lazy initialization of ChromaDB persistent client."""
        if self._collection is not None:
            return

        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=Settings(allow_reset=True, anonymized_telemetry=False)
        )
        self._collection = self._client.get_or_create_collection(
            name="pandas_table_schemas",
            metadata={"hnsw:space": "cosine"}
        )

    def extract_csv_files(self, query: str, top_k: int = 1) -> List[Dict]:
        """Query Vector DB and extract matching .csv file metadata for user query.
        
        Args:
            query: User query or table name
            top_k: Max number of matched CSV files to return
            
        Returns:
            List of metadata dicts containing file_name, file_path, and similarity_score.
        """
        self._init_chroma()

        if self._collection.count() == 0:
            return []

        results = self._collection.query(
            query_texts=[query],
            n_results=top_k
        )

        matched_csvs = []
        if results and results.get("metadatas"):
            for i, meta in enumerate(results["metadatas"][0]):
                file_path = meta.get("file_path", "")
                if file_path.endswith(".csv") or meta.get("file_name", "").endswith(".csv"):
                    distance = results["distances"][0][i] if results.get("distances") else 0.0
                    matched_csvs.append({
                        "file_name": meta.get("file_name"),
                        "file_path": file_path,
                        "similarity_score": round(1.0 - float(distance), 4),
                    })

        return matched_csvs
