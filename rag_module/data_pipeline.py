"""
data_pipeline.py
================
ViFinQA End-to-End Data Pipeline (ETL + Indexing).

Combines Phase 1 (ETL: extract HTML tables -> CSV) and Phase 2 (Index: embed
into Qdrant local DB + build BM25 index) into a single script.

Pipeline phases:
    Phase 1 – ETL
        A. Load ticker -> company name map from code_stock.csv
        B. Discover all *_extracted.txt files under financial_statements/
        C. Parse HTML tables (BeautifulSoup + lxml) -> pandas DataFrames
        D. Attach metadata columns (ticker, year, report type, unit, etc.)
        E. Write one CSV per table under processed_data/

    Phase 2 – Indexing
        F. Load all CSVs from processed_data/
        G. Build rich content strings (table name + metadata + line items)
        H. Encode with sentence-transformers -> upsert to Qdrant local DB
        I. Build BM25Okapi index -> save to bm25_index.pkl

Usage (local):
    python rag_module/data_pipeline.py

Usage (override paths):
    python rag_module/data_pipeline.py \\
        --base-dir . \\
        --processed-dir processed_data \\
        --qdrant-db-path rag_module/qdrant_local_db \\
        --bm25-path rag_module/bm25_index.pkl \\
        --batch-size 64

NOTE: Qdrant runs in LOCAL DISK MODE (no Docker, no server).
      The database is persisted as a folder on disk.
"""

from __future__ import annotations

import argparse
import io
import logging
import pickle
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import pandas as pd
from bs4 import BeautifulSoup, NavigableString, Tag
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# =============================================================================
# CONFIGURATION
# =============================================================================
# All paths are RELATIVE to the project root (where you run this script from).
# Change these to absolute paths if needed.

# =============================================================================
# PRODUCTION
# =============================================================================
# --- Input ---
# BASE_DIR                 = Path("./ViFinQA")                    # project root
# FINANCIAL_STATEMENTS_DIR = BASE_DIR / "financial_statements"
# CODE_STOCK_CSV           = Path(__file__).parent / "code_stock.csv"  # inside rag_module/

# --- ETL output ---
# PROCESSED_DATA_DIR       = BASE_DIR / "processed_data"

# --- Index output (bundled inside rag_module/ for Kaggle upload) ---
# _MODULE_DIR              = Path(__file__).parent        # rag_module/
# QDRANT_DB_PATH           = _MODULE_DIR / "qdrant_local_db"
# BM25_OUTPUT_PATH         = _MODULE_DIR / "bm25_index.pkl"

# --- Kaggle override (uncomment and set your dataset name) ---
# _KAGGLE_ROOT          = Path("/kaggle/input/your-dataset-name/rag_module")
# QDRANT_DB_PATH        = _KAGGLE_ROOT / "qdrant_local_db"
# BM25_OUTPUT_PATH      = _KAGGLE_ROOT / "bm25_index.pkl"
# CODE_STOCK_CSV        = _KAGGLE_ROOT / "code_stock.csv"

# --- Qdrant + Embedding ---
# COLLECTION_NAME          = "financial_tables"
# EMBEDDING_MODEL_NAME     = "paraphrase-multilingual-MiniLM-L12-v2"
# VECTOR_DIM               = 384
# BATCH_SIZE               = 64            # encoding + Qdrant upsert batch size

# =============================================================================
# TESTING
# =============================================================================

BASE_DIR                 = Path("./ViFinQA")                    # project root
FINANCIAL_STATEMENTS_DIR = BASE_DIR / "test_folder"
CODE_STOCK_CSV           = Path(__file__).parent / "code_stock.csv"  # inside rag_module/

# --- ETL output ---
PROCESSED_DATA_DIR       = BASE_DIR / "test/processed_data"

# --- Index output (bundled inside rag_module/ for Kaggle upload) ---
_MODULE_DIR              = Path(__file__).parent        # rag_module/
QDRANT_DB_PATH           = _MODULE_DIR / "test/qdrant_local_db"
BM25_OUTPUT_PATH         = _MODULE_DIR / "test/bm25_index.pkl"

# --- Kaggle override (uncomment and set your dataset name) ---
# _KAGGLE_ROOT          = Path("/kaggle/input/your-dataset-name/rag_module")
# QDRANT_DB_PATH        = _KAGGLE_ROOT / "qdrant_local_db"
# BM25_OUTPUT_PATH      = _KAGGLE_ROOT / "bm25_index.pkl"
# CODE_STOCK_CSV        = _KAGGLE_ROOT / "code_stock.csv"

# --- Qdrant + Embedding ---
COLLECTION_NAME          = "test_financial_tables"
EMBEDDING_MODEL_NAME     = "paraphrase-multilingual-MiniLM-L12-v2"
VECTOR_DIM               = 384
BATCH_SIZE               = 64            # encoding + Qdrant upsert batch size


# --- Metadata column names (must match ETL output exactly) ---
META_COLS: List[str] = [
    "Ma_Doanh_Nghiep",
    "Ten_Doanh_Nghiep",
    "Nam_Tai_Chinh",
    "Loai_Bao_Cao",
    "Ten_Bang",
    "Don_Vi_Tinh",
    "Tep_Nguon",
]

# =============================================================================
# Logging
# =============================================================================

def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

logger = logging.getLogger("data_pipeline")

# =============================================================================
# Vietnamese unit patterns for Don_Vi_Tinh extraction
# =============================================================================

_UNIT_PATTERNS: List[re.Pattern] = [
    re.compile(r"(Ty\s+dong)", re.IGNORECASE),
    re.compile(r"(Trieu\s+dong)", re.IGNORECASE),
    re.compile(r"(Nghin\s+dong)", re.IGNORECASE),
    re.compile(r"(Tỷ\s+đồng)", re.IGNORECASE),
    re.compile(r"(Triệu\s+đồng)", re.IGNORECASE),
    re.compile(r"(Nghìn\s+đồng)", re.IGNORECASE),
    re.compile(r"\b(VND)\b", re.IGNORECASE),
    re.compile(r"\b(USD)\b", re.IGNORECASE),
    re.compile(r"\b(EUR)\b", re.IGNORECASE),
    re.compile(r"(đồng Việt Nam)", re.IGNORECASE),
    re.compile(r"(đồng)", re.IGNORECASE),
]

_TOKEN_SPLIT = re.compile(r"[\s\.,;:()\[\]{}/\\\"'!?]+")

# =============================================================================
# PHASE 1 — ETL
# =============================================================================

# ---------------------------------------------------------------------------
# 1A. Load ticker map
# ---------------------------------------------------------------------------

def load_ticker_map(csv_path: Path) -> Dict[str, str]:
    """Load code_stock.csv -> {ticker: company_name}."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"code_stock.csv not found: {csv_path}")
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    col_map: Dict[str, str] = {}
    for col in df.columns:
        stripped = col.strip()
        if "CK" in stripped.upper() or "MÃ" in stripped.upper() or "MA" in stripped.upper():
            col_map["ticker"] = col
        if "TÊN" in stripped.upper() or "TEN" in stripped.upper() or "CÔNG" in stripped.upper():
            col_map["name"] = col
    if "ticker" not in col_map or "name" not in col_map:
        cols = list(df.columns)
        col_map["ticker"], col_map["name"] = cols[0], cols[1]
    ticker_map = dict(zip(
        df[col_map["ticker"]].astype(str).str.strip(),
        df[col_map["name"]].astype(str).str.strip(),
    ))
    logger.info("Loaded %d tickers from %s", len(ticker_map), csv_path)
    return ticker_map


# ---------------------------------------------------------------------------
# 1B. Discover source files
# ---------------------------------------------------------------------------

def iter_txt_files(statements_dir: Path) -> List[Path]:
    """Recursively find all *_extracted.txt files."""
    if not statements_dir.is_dir():
        raise FileNotFoundError(f"Directory not found: {statements_dir}")
    files = sorted(statements_dir.rglob("*_extracted.txt"))
    logger.info("Discovered %d extracted text files under %s", len(files), statements_dir)
    return files


def extract_metadata_from_path(file_path: Path) -> Tuple[str, str, str]:
    """
    Derive (ticker, year, report_type) from the file path.

    Expected structure (production):
        financial_statements/<TICKER>/<YEAR>/<TICKER>_..._<TYPE>/<file>
    Also handles shorter test layouts where the <TICKER> directory is absent:
        test_folder/<YEAR>/<TICKER>_..._<TYPE>/<file>

    The ticker is always extracted from the doc-folder name (the directory
    directly containing the file), which reliably starts with
    ``<TICKER>_financial_statements_…``.

    report_type: 'consolidated' | 'separate' | 'unknown'
    """
    _SKIP_PARTS = {"test", "test_folder"}
    parts = [p for p in file_path.parts if p.lower() not in _SKIP_PARTS]

    doc_folder = parts[-2] if len(parts) >= 2 else ""

    # Ticker: first segment of the doc-folder name (e.g. "PC1_financial_…" → "PC1")
    ticker = doc_folder.split("_")[0] if doc_folder else "UNKNOWN"

    # Year: extract the 4-digit number (handles "2015 copy", "2023", etc.)
    raw_year = parts[-3] if len(parts) >= 3 else "UNKNOWN"
    year_match = re.search(r"(\d{4})", raw_year)
    year = year_match.group(1) if year_match else raw_year

    report_type = "unknown"
    for kw in ("consolidated", "separate"):
        if kw in doc_folder.lower():
            report_type = kw
            break
    return ticker, year, report_type


# ---------------------------------------------------------------------------
# 1C-D. HTML table parsing & metadata attachment
# ---------------------------------------------------------------------------

def _get_preceding_text_lines(tag: Tag, n: int = 5) -> str:
    """Collect up to *n* non-empty text lines appearing before a <table> tag.

    Lines are delimited by <br> tags that were inserted during preprocessing.
    """
    collected: List[str] = []
    current_parts: List[str] = []
    sibling = tag.previous_sibling
    while sibling is not None and len(collected) < n:
        if isinstance(sibling, Tag) and sibling.name == "br":
            line = " ".join(current_parts).strip()
            if line:
                collected.append(line)
            current_parts = []
        elif isinstance(sibling, NavigableString):
            text = str(sibling).strip()
            if text:
                current_parts.insert(0, text)
        sibling = sibling.previous_sibling
    # Remaining text before the first <br> encountered
    line = " ".join(current_parts).strip()
    if line and len(collected) < n:
        collected.append(line)
    # collected is closest-first; reverse to chronological order
    collected.reverse()
    return "\n".join(collected)


def clean_line_noise(line: str) -> str:
    """Strip inline noise (units, templates, page separators) from a line, keeping the rest."""
    # 1. Strip unit of measurement declarations and everything after them
    line = re.sub(r"\b(?:đơn\s+vị\s+tính|đvt)\b.*", "", line, flags=re.IGNORECASE)
    line = re.sub(r"\bđơn\s+vị\b\s*(?::|-|là)\s*\w+.*", "", line, flags=re.IGNORECASE)

    # 2. Strip template headers, publication notes, page separators, dates
    line = re.sub(
        r"\b(?:mẫu\s+b\s*\d+.*|ban\s+hành\s+kèm\s+theo.*|ban\s+hành\s+ngày.*|"
        r"ngày\s+\d{1,2}/\d{1,2}/\d{4}.*|===\s*PAGE.*)",
        "",
        line,
        flags=re.IGNORECASE
    )

    # Clean up dangling punctuation & outer whitespace
    line = line.strip()
    line = re.sub(r"^[-–—\s,\.:;\(\)\[\]]+|[-–—\s,\.:;\(\)\[\]]+$", "", line)
    return line.strip()


def extract_table_name(pre_text: str) -> str:
    """Extract a table heading from preceding context using bottom-up scan.

    Starting from the line closest to the table and moving upward:
    - Inline noise (like unit declarations, templates) is stripped from lines.
    - If the cleaned line becomes empty or matches generic number/page patterns, it is skipped.
    - Lines entirely wrapped in parentheses (e.g. ``(Theo phương pháp trực tiếp)``)
      are collected as trailing suffixes and skipped.
    - The first remaining (valid) line becomes the main heading; the line
      directly above it is also cleaned and included if valid.
    """
    lines = [ln.strip() for ln in pre_text.splitlines()]

    _PAREN_RE = re.compile(r"^\(.*\)$")
    _FULL_LINE_NOISE = re.compile(
        r"^(?:\d+|[\d\.\-\/,\s]+|page.*)$",
        re.IGNORECASE
    )

    suffixes: List[str] = []

    for i in range(len(lines) - 1, -1, -1):
        raw_line = lines[i]
        if not raw_line:
            continue

        cleaned = clean_line_noise(raw_line)
        if not cleaned or _FULL_LINE_NOISE.match(cleaned):
            continue

        if _PAREN_RE.match(cleaned):
            suffixes.append(cleaned)
            continue

        # Found the valid line — also grab the cleaned line above if meaningful
        parts: List[str] = []
        if i > 0:
            cleaned_prev = clean_line_noise(lines[i - 1])
            if cleaned_prev and not _FULL_LINE_NOISE.match(cleaned_prev) and not _PAREN_RE.match(cleaned_prev):
                parts.append(cleaned_prev)
        parts.append(cleaned)
        suffixes.reverse()
        parts.extend(suffixes)
        return " ".join(parts)

    return ""


def extract_unit(pre_text: str) -> str:
    """Extract monetary unit from preceding context text."""
    for pattern in _UNIT_PATTERNS:
        m = pattern.search(pre_text)
        if m:
            return m.group(1).strip()
    return ""


def parse_tables_from_content(
    content: str,
) -> Generator[Tuple[int, Tag, str, str, str], None, None]:
    """
    Parse all <table> tags from raw text using BeautifulSoup + lxml.
    NOTE: Regex is NOT used to parse HTML (project rule).
    """
    soup = BeautifulSoup(content, "lxml")
    for idx, table_tag in enumerate(soup.find_all("table")):
        pre_text   = _get_preceding_text_lines(table_tag, n=5)
        table_name = extract_table_name(pre_text)
        unit       = extract_unit(pre_text)
        yield idx, table_tag, pre_text, table_name, unit


def table_tag_to_dataframe(table_tag: Tag) -> Optional[pd.DataFrame]:
    """Convert a BeautifulSoup <table> Tag to a pandas DataFrame."""
    try:
        dfs = pd.read_html(io.StringIO(str(table_tag)))
        return dfs[0] if dfs else None
    except ValueError as exc:
        logger.debug("Skipping malformed/empty table: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected error parsing table: %s", exc)
        return None


def attach_metadata(
    df: pd.DataFrame,
    ticker: str, company_name: str, year: str,
    report_type: str, table_name: str, unit: str, source_ref: str,
) -> pd.DataFrame:
    """Prepend standardised metadata columns using a single pd.concat call."""
    n = len(df)
    meta_df = pd.DataFrame({
        "Ma_Doanh_Nghiep":  [ticker]       * n,
        "Ten_Doanh_Nghiep": [company_name]  * n,
        "Nam_Tai_Chinh":    [year]          * n,
        "Loai_Bao_Cao":     [report_type]   * n,
        "Ten_Bang":         [table_name]    * n,
        "Don_Vi_Tinh":      [unit]          * n,
        "Tep_Nguon":        [source_ref]    * n,
    })
    return pd.concat([meta_df, df.reset_index(drop=True)], axis=1)


def process_txt_file(
    file_path: Path,
    ticker_map: Dict[str, str],
) -> List[pd.DataFrame]:
    """Full ETL for one *_extracted.txt file -> list of enriched DataFrames."""
    ticker, year, report_type = extract_metadata_from_path(file_path)
    company_name = ticker_map.get(ticker, "")
    if not company_name:
        logger.warning("Ticker '%s' not found in code_stock.csv.", ticker)

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        # Insert <br> before each newline so BeautifulSoup preserves line breaks
        content = content.replace("\n", "<br>\n")
    except OSError as exc:
        logger.error("Cannot read %s: %s", file_path, exc)
        return []

    tables: List[pd.DataFrame] = []
    for idx, table_tag, _, table_name, unit in parse_tables_from_content(content):
        df = table_tag_to_dataframe(table_tag)
        if df is None:
            continue
        source_ref = f"{file_path.as_posix()}#table_{idx}"
        df = attach_metadata(df, ticker, company_name, year,
                             report_type, table_name, unit, source_ref)
        tables.append(df)
    return tables


# ---------------------------------------------------------------------------
# 1E. Save CSVs
# ---------------------------------------------------------------------------

def build_csv_output_path(
    file_path: Path,
    statements_dir: Path,
    output_dir: Path,
    table_index: int,
) -> Path:
    """Mirror the source path under output_dir, replacing .txt with _table_N.csv."""
    relative = file_path.relative_to(statements_dir).with_suffix("")
    stem = relative.name
    if stem.endswith("_extracted"):
        stem = stem[: -len("_extracted")]
    return output_dir / relative.parent / f"{stem}_table_{table_index}.csv"


def run_etl(
    statements_dir: Path,
    processed_dir: Path,
    ticker_map: Dict[str, str],
) -> int:
    """Run Phase 1: discover txt files -> parse tables -> write CSVs."""
    txt_files = iter_txt_files(statements_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)

    total_csv = 0
    failed: List[Path] = []

    logger.info("Phase 1 — ETL: processing %d source files …", len(txt_files))
    for file_path in tqdm(txt_files, desc="Phase 1 ETL", unit="file"):
        try:
            tables = process_txt_file(file_path, ticker_map)
        except Exception as exc:
            logger.error("Unhandled error processing %s: %s", file_path, exc)
            failed.append(file_path)
            continue

        for df in tables:
            try:
                anchor_idx = int(df["Tep_Nguon"].iloc[0].split("#table_")[1])
            except (IndexError, ValueError):
                anchor_idx = 0
            csv_path = build_csv_output_path(
                file_path, statements_dir, processed_dir, anchor_idx
            )
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            total_csv += 1

    logger.info("Phase 1 complete. CSVs written: %d  |  Failed files: %d",
                total_csv, len(failed))
    return total_csv


# =============================================================================
# PHASE 2 — INDEXING
# =============================================================================

# ---------------------------------------------------------------------------
# 2A. Content string builder
# ---------------------------------------------------------------------------

def build_rich_content_string(df: pd.DataFrame, meta: Dict[str, str]) -> str:
    """
    Build a semantically rich Vietnamese string for embedding + BM25.

    Includes up to 50 unique financial line item labels from the first
    data column (e.g. 'Lợi nhuận sau thuế', 'Doanh thu thuần').
    """
    data_cols = [c for c in df.columns if c not in META_COLS]
    line_items: List[str] = []
    if data_cols:
        try:
            line_items = (
                df[data_cols[0]].dropna().astype(str).str.strip()
                .loc[lambda s: s.str.len() > 2]
                .drop_duplicates().head(50).tolist()
            )
        except Exception:
            pass

    parts = [
        f"Bảng {meta.get('Ten_Bang', '')} "
        f"của công ty {meta.get('Ten_Doanh_Nghiep', '')} "
        f"({meta.get('Ma_Doanh_Nghiep', '')}) "
        f"năm {meta.get('Nam_Tai_Chinh', '')}.",
        f"Loại báo cáo: {meta.get('Loai_Bao_Cao', '')}.",
        f"Đơn vị tính: {meta.get('Don_Vi_Tinh', '')}.",
    ]
    if line_items:
        parts.append(f"Các chỉ tiêu: {', '.join(line_items)}")
    return " ".join(parts)


def tokenize(text: str) -> List[str]:
    """Tokenise Vietnamese text for BM25 (lowercase + split on punctuation)."""
    return [t for t in _TOKEN_SPLIT.split(text.lower()) if len(t) >= 2]


# ---------------------------------------------------------------------------
# 2B. Qdrant setup
# ---------------------------------------------------------------------------

def setup_qdrant_collection(client: QdrantClient, name: str, dim: int) -> None:
    """Delete (if exists) and recreate a Qdrant collection with Cosine distance."""
    existing = [c.name for c in client.get_collections().collections]
    if name in existing:
        logger.warning("Collection '%s' exists — deleting and recreating.", name)
        client.delete_collection(name)
    client.create_collection(
        collection_name=name,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    logger.info("Qdrant collection '%s' created (dim=%d, Cosine).", name, dim)


# ---------------------------------------------------------------------------
# 2C. Main indexing orchestrator
# ---------------------------------------------------------------------------

def run_indexing(
    processed_dir: Path,
    qdrant_db_path: Path,
    bm25_path: Path,
    collection_name: str = COLLECTION_NAME,
    embedding_model: str = EMBEDDING_MODEL_NAME,
    vector_dim: int = VECTOR_DIM,
    batch_size: int = BATCH_SIZE,
) -> None:
    """
    Run Phase 2: load CSVs -> embed -> upsert Qdrant local DB -> build BM25.

    Qdrant runs in LOCAL DISK MODE: QdrantClient(path=qdrant_db_path).
    No Docker or server required.
    """
    # --- Qdrant (local disk mode) ---
    qdrant_db_path.mkdir(parents=True, exist_ok=True)
    logger.info("Qdrant local DB path: %s", qdrant_db_path)
    qdrant = QdrantClient(path=str(qdrant_db_path))
    setup_qdrant_collection(qdrant, collection_name, vector_dim)

    # --- Embedding model ---
    logger.info("Loading embedding model: %s", embedding_model)
    model = SentenceTransformer(embedding_model)

    # --- Discover CSVs ---
    if not processed_dir.is_dir():
        raise FileNotFoundError(
            f"processed_data/ not found: {processed_dir}\n"
            "Run Phase 1 (ETL) first."
        )
    csv_files = sorted(processed_dir.rglob("*.csv"))
    logger.info("Found %d CSV files under %s", len(csv_files), processed_dir)

    # --- Phase 2A: Parse CSVs -> content strings ---
    content_strings: List[str]          = []
    payloads:        List[Dict[str, Any]] = []
    skipped = 0

    logger.info("Phase 2A — Parsing CSVs …")
    for csv_path in tqdm(csv_files, desc="Parsing CSVs", unit="file"):
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
        except Exception as exc:
            logger.error("Cannot read %s: %s", csv_path, exc)
            skipped += 1
            continue
        if df.empty:
            skipped += 1
            continue

        first_row = df.iloc[0]
        meta = {col: str(first_row[col]).strip() if col in df.columns else ""
                for col in META_COLS}

        content_str = build_rich_content_string(df, meta)
        data_cols   = [c for c in df.columns if c not in META_COLS]
        line_items  = ""
        if data_cols:
            try:
                line_items = ", ".join(
                    df[data_cols[0]].dropna().astype(str).str.strip()
                    .loc[lambda s: s.str.len() > 2]
                    .drop_duplicates().head(50).tolist()
                )
            except Exception:
                pass

        content_strings.append(content_str)
        payloads.append({
            **meta,
            "csv_path":   csv_path.as_posix(),
            "row_count":  len(df),
            "col_count":  len(data_cols),
            "line_items": line_items,
        })

    logger.info("Phase 2A complete. Documents: %d  |  Skipped: %d",
                len(content_strings), skipped)

    # --- Phase 2B: Encode vectors ---
    logger.info("Phase 2B — Encoding %d documents …", len(content_strings))
    vectors = model.encode(
        content_strings,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    logger.info("Phase 2B complete. Vectors shape: %s", vectors.shape)

    # --- Phase 2C: Build Qdrant points + BM25 corpus ---
    qdrant_points: List[PointStruct]    = []
    bm25_corpus:   List[List[str]]      = []
    doc_mapping:   List[Dict[str, Any]] = []

    for i, (content_str, payload, vector) in enumerate(
        zip(content_strings, payloads, vectors)
    ):
        point_id = str(uuid.uuid4())
        qdrant_points.append(PointStruct(
            id=point_id, vector=vector.tolist(), payload=payload
        ))
        bm25_corpus.append(tokenize(content_str))
        doc_mapping.append({
            "bm25_idx": i, "qdrant_id": point_id,
            "content_string": content_str, **payload,
        })

    # --- Phase 2D: Upload to Qdrant ---
    logger.info("Phase 2D — Uploading %d points to Qdrant …", len(qdrant_points))
    uploaded = 0
    for start in tqdm(range(0, len(qdrant_points), batch_size),
                      desc="Uploading to Qdrant", unit="batch"):
        batch = qdrant_points[start: start + batch_size]
        qdrant.upsert(collection_name=collection_name, points=batch)
        uploaded += len(batch)
    logger.info("Phase 2D complete. %d points uploaded.", uploaded)

    # --- Phase 2E: BM25 ---
    logger.info("Phase 2E — Building BM25 index over %d documents …", len(bm25_corpus))
    bm25 = BM25Okapi(bm25_corpus)
    bm25_path.parent.mkdir(parents=True, exist_ok=True)
    with open(bm25_path, "wb") as f:
        pickle.dump({"bm25": bm25, "doc_mapping": doc_mapping}, f,
                    protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("BM25 index saved -> %s  (%d docs)", bm25_path, len(bm25_corpus))

    # --- Summary ---
    logger.info("=" * 64)
    logger.info("Indexing complete.")
    logger.info("  Qdrant DB    : %s  (%d points)", qdrant_db_path, uploaded)
    logger.info("  BM25 index   : %s  (%d docs)",   bm25_path, len(bm25_corpus))
    logger.info("=" * 64)


# =============================================================================
# FULL PIPELINE ORCHESTRATOR
# =============================================================================

def run_pipeline(
    base_dir:       Path = BASE_DIR,
    statements_dir: Path = FINANCIAL_STATEMENTS_DIR,
    processed_dir:  Path = PROCESSED_DATA_DIR,
    qdrant_db_path: Path = QDRANT_DB_PATH,
    bm25_path:      Path = BM25_OUTPUT_PATH,
    code_stock_csv: Path = CODE_STOCK_CSV,
    batch_size:     int  = BATCH_SIZE,
    skip_etl:       bool = False,
    do_indexing:    bool = False,
) -> None:
    """Run the complete ETL + Indexing pipeline end to end."""
    logger.info("=" * 64)
    logger.info("ViFinQA Data Pipeline")
    logger.info("  Source     : %s", statements_dir.resolve())
    logger.info("  Processed  : %s", processed_dir.resolve())
    logger.info("  Qdrant DB  : %s", qdrant_db_path.resolve())
    logger.info("  BM25       : %s", bm25_path.resolve())
    logger.info("=" * 64)

    ticker_map = load_ticker_map(code_stock_csv)

    if not skip_etl:
        run_etl(statements_dir, processed_dir, ticker_map)
    else:
        logger.info("Skipping ETL phase (--skip-etl flag set).")

    if do_indexing:
        run_indexing(
            processed_dir=processed_dir,
            qdrant_db_path=qdrant_db_path,
            bm25_path=bm25_path,
            batch_size=batch_size,
        )
    else:
        logger.info("Skipping Indexing phase (use --run-indexing to enable).")


# =============================================================================
# CLI
# =============================================================================

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="data_pipeline",
        description="ViFinQA end-to-end data pipeline (ETL + Indexing).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--base-dir",        type=Path, default=BASE_DIR)
    p.add_argument("--statements-dir",  type=Path, default=FINANCIAL_STATEMENTS_DIR)
    p.add_argument("--processed-dir",   type=Path, default=PROCESSED_DATA_DIR)
    p.add_argument("--qdrant-db-path",  type=Path, default=QDRANT_DB_PATH)
    p.add_argument("--bm25-path",       type=Path, default=BM25_OUTPUT_PATH)
    p.add_argument("--code-stock-csv",  type=Path, default=CODE_STOCK_CSV)
    p.add_argument("--batch-size",      type=int,  default=BATCH_SIZE)
    p.add_argument("--skip-etl",        action="store_true",
                   help="Skip Phase 1 (ETL) and go straight to indexing.")
    p.add_argument("--run-indexing",     action="store_true",
                   help="Also run Phase 2 (Indexing) after ETL.")
    p.add_argument("--log-level",       type=str,  default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)
    configure_logging(args.log_level)
    run_pipeline(
        base_dir=args.base_dir.resolve(),
        statements_dir=args.statements_dir.resolve(),
        processed_dir=args.processed_dir.resolve(),
        qdrant_db_path=args.qdrant_db_path.resolve(),
        bm25_path=args.bm25_path.resolve(),
        code_stock_csv=args.code_stock_csv.resolve(),
        batch_size=args.batch_size,
        skip_etl=args.skip_etl,
        do_indexing=args.run_indexing,
    )


if __name__ == "__main__":
    main()

