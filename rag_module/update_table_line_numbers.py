"""
update_table_line_numbers.py
=============================
Script to update table names (Ten_Bang), source files (Tep_Nguon), and line numbers (table_line/source_line)
in Qdrant Local DB and BM25 index using the processed CSV files located under:
    rag_module/ViFinQA/processed_data
"""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
from qdrant_client import QdrantClient
from tqdm import tqdm

_HERE = Path(__file__).parent.resolve()
PROCESSED_DATA_DIR = _HERE / "ViFinQA" / "processed_data"
if not PROCESSED_DATA_DIR.exists():
    PROCESSED_DATA_DIR = _HERE / "processed_data"

QDRANT_DB_PATH = _HERE / "qdrant_local_db"
if not QDRANT_DB_PATH.exists():
    QDRANT_DB_PATH = _HERE / "test" / "qdrant_local_db"

BM25_PATH = _HERE / "bm25_index.pkl"
if not BM25_PATH.exists():
    BM25_PATH = _HERE / "test" / "bm25_index.pkl"

COLLECTION_NAME = "financial_tables"


def extract_line_number(tep_nguon: str, csv_path: Path) -> int:
    """Extract integer line number from Tep_Nguon or filename @line_N."""
    m = re.search(r"@line_(\d+)", tep_nguon)
    if m:
        return int(m.group(1))
    m_file = re.search(r"@line_(\d+)", csv_path.name)
    if m_file:
        return int(m_file.group(1))
    return 1


def normalize_rel_path(p_str: str) -> str:
    """Normalize file path to unix relative path under processed_data."""
    p_str = p_str.replace("\\", "/")
    if "processed_data/" in p_str:
        return p_str.split("processed_data/")[-1]
    return Path(p_str).name


def main():
    print(f"1. Scanning CSV files under: {PROCESSED_DATA_DIR}")
    if not PROCESSED_DATA_DIR.exists():
        raise FileNotFoundError(f"Processed data directory not found: {PROCESSED_DATA_DIR}")

    csv_files = list(PROCESSED_DATA_DIR.rglob("*.csv"))
    print(f"Found {len(csv_files)} CSV files in {PROCESSED_DATA_DIR}.")

    # Build mapping dicts from processed CSV files
    # Key 1: relative CSV path (e.g. AAA/2015/.../table_1@line_214.csv)
    # Key 2: Tep_Nguon base anchor (e.g. AAA_financial_statements_2015_consolidated_extracted.txt#table_1)
    csv_meta_by_relpath: Dict[str, Dict[str, Any]] = {}
    csv_meta_by_base_tep: Dict[str, Dict[str, Any]] = {}

    print("Reading metadata from processed CSV files...")
    for csv_file in tqdm(csv_files, desc="Reading CSV metadata"):
        try:
            df = pd.read_csv(csv_file, nrows=1, dtype=str)
            if df.empty:
                continue
            row = df.iloc[0]
            ten_bang = str(row.get("Ten_Bang", "")).strip()
            tep_nguon = str(row.get("Tep_Nguon", "")).strip()
            line_num = extract_line_number(tep_nguon, csv_file)

            rel_path = normalize_rel_path(csv_file.as_posix())
            base_tep = re.sub(r"@line_\d+", "", tep_nguon).strip()

            meta_info = {
                "Ten_Bang": ten_bang,
                "Tep_Nguon": tep_nguon,
                "table_line": line_num,
                "source_line": line_num,
                "csv_path": csv_file.as_posix(),
            }

            csv_meta_by_relpath[rel_path] = meta_info
            if base_tep:
                csv_meta_by_base_tep[base_tep] = meta_info
        except Exception as e:
            print(f"Warning reading {csv_file}: {e}")

    print(f"Metadata loaded: {len(csv_meta_by_relpath)} unique CSV relative paths.")

    # 2. Connect to Qdrant Local DB
    print(f"\n2. Connecting to Qdrant DB at: {QDRANT_DB_PATH}")
    qdrant = QdrantClient(path=str(QDRANT_DB_PATH))

    print(f"Fetching points from collection '{COLLECTION_NAME}'...")
    all_points = []
    offset = None
    while True:
        res, next_offset = qdrant.scroll(
            collection_name=COLLECTION_NAME,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        all_points.extend(res)
        if next_offset is None:
            break
        offset = next_offset

    print(f"Total Qdrant points fetched: {len(all_points)}")

    # 3. Update Qdrant payloads with new table names from processed_data
    print("\n3. Updating Qdrant payloads with table names from processed_data...")
    updated_qdrant_count = 0
    matched_qdrant_count = 0

    for pt in tqdm(all_points, desc="Updating Qdrant points"):
        p = pt.payload or {}
        pt_csv = p.get("csv_path", "")
        pt_tep = p.get("Tep_Nguon", "")

        rel_path = normalize_rel_path(str(pt_csv))
        base_tep = re.sub(r"@line_\d+", "", str(pt_tep)).strip()

        meta = csv_meta_by_relpath.get(rel_path) or csv_meta_by_base_tep.get(base_tep)

        if meta:
            matched_qdrant_count += 1
            new_payload = {
                "Ten_Bang": meta["Ten_Bang"],
                "Tep_Nguon": meta["Tep_Nguon"],
                "table_line": meta["table_line"],
                "source_line": meta["source_line"],
                "csv_path": meta["csv_path"],
            }
            qdrant.set_payload(
                collection_name=COLLECTION_NAME,
                payload=new_payload,
                points=[pt.id],
            )
            updated_qdrant_count += 1
        else:
            # Fallback if CSV path doesn't match directly: format line number if present
            orig_ten = str(p.get("Ten_Bang", ""))
            orig_tep = str(p.get("Tep_Nguon", ""))
            l_num = extract_line_number(orig_tep, Path(pt_csv))
            base_ten = re.sub(r"\s*@line_\d+", "", orig_ten).strip()
            base_tep_clean = re.sub(r"@line_\d+", "", orig_tep).strip()

            new_ten = f"{base_ten} @line_{l_num}" if base_ten else f"Table @line_{l_num}"
            new_tep = f"{base_tep_clean}@line_{l_num}"

            qdrant.set_payload(
                collection_name=COLLECTION_NAME,
                payload={
                    "Ten_Bang": new_ten,
                    "Tep_Nguon": new_tep,
                    "table_line": l_num,
                    "source_line": l_num,
                },
                points=[pt.id],
            )
            updated_qdrant_count += 1

    print(f"Finished Qdrant update: {updated_qdrant_count} points updated ({matched_qdrant_count} matched directly with processed_data CSVs).")

    # 4. Synchronize BM25 Index
    if BM25_PATH.exists():
        print(f"\n4. Synchronizing BM25 index at: {BM25_PATH}")
        with open(BM25_PATH, "rb") as f:
            bm25_data = pickle.load(f)

        doc_mapping = bm25_data.get("doc_mapping", [])
        bm25_updated = 0
        for doc in doc_mapping:
            doc_csv = doc.get("csv_path", "")
            doc_tep = doc.get("Tep_Nguon", "")

            rel_path = normalize_rel_path(str(doc_csv))
            base_tep = re.sub(r"@line_\d+", "", str(doc_tep)).strip()

            meta = csv_meta_by_relpath.get(rel_path) or csv_meta_by_base_tep.get(base_tep)

            if meta:
                doc["Ten_Bang"] = meta["Ten_Bang"]
                doc["Tep_Nguon"] = meta["Tep_Nguon"]
                doc["table_line"] = meta["table_line"]
                doc["source_line"] = meta["source_line"]
                doc["csv_path"] = meta["csv_path"]
            else:
                l_num = extract_line_number(str(doc_tep), Path(doc_csv))
                base_ten = re.sub(r"\s*@line_\d+", "", str(doc.get("Ten_Bang", ""))).strip()
                base_tep_clean = re.sub(r"@line_\d+", "", str(doc_tep)).strip()

                doc["Ten_Bang"] = f"{base_ten} @line_{l_num}" if base_ten else f"Table @line_{l_num}"
                doc["Tep_Nguon"] = f"{base_tep_clean}@line_{l_num}"
                doc["table_line"] = l_num
                doc["source_line"] = l_num
            bm25_updated += 1

        with open(BM25_PATH, "wb") as f:
            pickle.dump(bm25_data, f, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"Successfully synchronized {bm25_updated} entries in BM25 index.")

    print("\nUpdate process completed successfully!")


if __name__ == "__main__":
    main()
