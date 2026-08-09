"""Data registry utility to discover and index datasets across local and Kaggle environments."""

import os
from pathlib import Path
from typing import Dict, List, Optional
from thefuzz import process
import pandas as pd

from pipeline.src.config import Config, config as default_config, is_kaggle_environment


class DataRegistry:
    """Registry to manage and discover CSV/Excel files in workspace or Kaggle input."""

    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or default_config
        self.search_dirs: List[Path] = []
        self._init_search_dirs()

    def _init_search_dirs(self):
        """Initialize search directories based on execution environment."""
        # Workspace data dir
        if self.cfg.DATA_DIR.exists():
            self.search_dirs.append(self.cfg.DATA_DIR)

        # Kaggle input dir
        kaggle_input = Path("/kaggle/input")
        if kaggle_input.exists():
            self.search_dirs.append(kaggle_input)

    def scan_files(self) -> Dict[str, Path]:
        """Scan all available CSV and Excel files.
        
        Returns:
            Dict mapping file stem/name to absolute Path.
        """
        registry: Dict[str, Path] = {}

        for search_dir in self.search_dirs:
            for ext in ["*.csv", "*.xlsx", "*.xls"]:
                for file_path in search_dir.rglob(ext):
                    # Clean key: lowercase stem
                    key = file_path.stem.lower()
                    registry[key] = file_path.resolve()
                    # Also map full filename
                    registry[file_path.name.lower()] = file_path.resolve()

        return registry

    def find_best_match(self, query_filename: str, score_threshold: int = 50) -> Optional[Path]:
        """Find the best matching data file using fuzzy matching.
        
        Args:
            query_filename: Target filename/keyword from user query
            score_threshold: Minimum fuzzy similarity score (0-100)
            
        Returns:
            Path to matched file or None if no match above threshold.
        """
        registry = self.scan_files()
        if not registry:
            return None

        if not query_filename or query_filename == "null":
            # If user didn't specify filename, return first available file if only 1 exists
            if len(registry) == 1 or len(registry) == 2:  # 2 because stem and full name mapped
                return list(registry.values())[0]
            return list(registry.values())[0] if registry else None

        clean_query = query_filename.lower().strip()

        # Exact key match check first
        if clean_query in registry:
            return registry[clean_query]

        # Fuzzy match
        choices = list(registry.keys())
        match, score = process.extractOne(clean_query, choices)

        if score >= score_threshold:
            return registry[match]

        return None


def get_table_schema(file_path: Path, nrows: int = 5) -> Dict:
    """Extract schema metadata (columns, dtypes, sample rows) from a dataset.
    
    Args:
        file_path: Absolute path to CSV or Excel file.
        nrows: Number of sample rows to inspect.
        
    Returns:
        Dict containing column names, data types, row count, and sample data.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext == ".csv":
        df = pd.read_csv(file_path, nrows=nrows)
        total_rows = sum(1 for _ in open(file_path, encoding="utf-8", errors="ignore")) - 1
    else:
        df = pd.read_excel(file_path, nrows=nrows)
        total_rows = len(df)

    columns_info = {col: str(dtype) for col, dtype in df.dtypes.items()}
    sample_data = df.to_dict(orient="records")

    return {
        "file_name": file_path.name,
        "file_path": str(file_path),
        "total_columns": len(df.columns),
        "estimated_rows": total_rows,
        "columns": columns_info,
        "sample_rows": sample_data,
    }
