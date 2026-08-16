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
from typing import Any, Dict, Generator, List, Optional, Tuple, Set

import pandas as pd
from bs4 import BeautifulSoup, Tag
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
# PRODUCTION  (comment out this block and uncomment TESTING when developing)
# =============================================================================
# --- Input ---
# BASE_DIR                 = Path("./ViFinQA")
# FINANCIAL_STATEMENTS_DIR = BASE_DIR / "financial_statements"
# CODE_STOCK_CSV           = Path(__file__).parent / "code_stock.csv"

# # --- ETL output ---
# PROCESSED_DATA_DIR       = BASE_DIR / "processed_data"

# # --- Index output (bundled inside rag_module/ for Kaggle upload) ---
# _MODULE_DIR              = Path(__file__).parent
# QDRANT_DB_PATH           = _MODULE_DIR / "qdrant_local_db"
# BM25_OUTPUT_PATH         = _MODULE_DIR / "bm25_index.pkl"

# --- Kaggle override (uncomment and set your dataset name) ---
# _KAGGLE_ROOT          = Path("/kaggle/input/datasets/duymcminh/r2ai-rag-module")
# QDRANT_DB_PATH        = _KAGGLE_ROOT / "qdrant_local_db"
# BM25_OUTPUT_PATH      = _KAGGLE_ROOT / "bm25_index.pkl"
# CODE_STOCK_CSV        = _KAGGLE_ROOT / "code_stock.csv"

# =============================================================================
# TESTING  (currently active — switch to PRODUCTION block for full run)
# =============================================================================
BASE_DIR                 = Path("./ViFinQA")                          # project root
FINANCIAL_STATEMENTS_DIR = BASE_DIR / "test/statement"                # small test set
CODE_STOCK_CSV           = Path(__file__).parent / "code_stock.csv"   # inside rag_module/

# --- ETL output ---
PROCESSED_DATA_DIR       = BASE_DIR / "test/processed_data"

# --- Index output ---
_MODULE_DIR              = Path(__file__).parent        # rag_module/
QDRANT_DB_PATH           = _MODULE_DIR / "test/qdrant_local_db"
BM25_OUTPUT_PATH         = _MODULE_DIR / "test/bm25_index.pkl"

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

def _get_preceding_lines_from_raw(
    raw_lines: List[str],
    table_line: int,
    n: int = 15,
) -> str:
    """Return up to *n* raw source lines immediately above *table_line* (0-indexed).

    This replaces the old BeautifulSoup sibling walk.  Using the raw source
    line list (before <br> injection) gives a much wider and more accurate
    context window for table-name extraction.

    Args:
        raw_lines:  The source file split on newlines (before <br> injection).
        table_line: 0-indexed line number where the <table> tag begins.
        n:          How many lines above the table to include (default 15).

    Returns:
        A newline-joined string of the *n* lines above *table_line*.
    """
    start = max(0, table_line - n)
    end   = max(0, table_line)          # exclusive; don't include the table line itself
    lines = raw_lines[start:end]
    return "\n".join(lines)


def clean_line_noise(line: str) -> str:
    """Strip inline noise (units, templates, page separators, dates) from a line.

    Applied during the bottom-up scan in extract_table_name() so that lines
    like 'Đơn vị: VND', 'MÃU B 01-DN/HN', 'Tại ngày 31 tháng 12 năm 2015',
    'Cho năm tài chính kết thúc' are eliminated before finding the real heading.
    """
    # 1. Unit-of-measurement declarations (any variant of 'đơn vị')
    #    e.g. 'Đơn vị tính: VND', 'Đơn vị: VND', 'ĐVT: Triệu đồng'
    line = re.sub(r"(?i)\b(?:đơn\s+vị(?:\s+tính)?|đvt)\b.*", "", line)

    # 2. Vietnamese date/period phrases (entire line or trailing)
    #    e.g. 'Tại ngày 31 tháng 12 năm 2015'
    #         'ngày 31 tháng 12 năm 2020'
    #         'Cho năm tài chính kết thúc ngày ...'
    #         'Cho năm tài chính kết thúc'
    line = re.sub(r"(?i)\bTại\s+ngày\b.*", "", line)
    line = re.sub(r"(?i)\bngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}\b.*", "", line)
    line = re.sub(r"(?i)\bngày\s+\d{1,2}/\d{1,2}/\d{4}\b.*", "", line)
    line = re.sub(r"(?i)\bCho\s+(?:năm|kỳ)\s+tài\s+chính\b.*", "", line)
    line = re.sub(r"(?i)\bNăm\s+tài\s+chính\s+kết\s+thúc\b.*", "", line)

    # 3. Template / form codes
    #    e.g. 'MÃU B 01-DN/HN', 'Mẫu số B01-DN', 'Ban hành kèm theo ...'
    #    Note: use a character class that handles both accented (MÃU) and unaccented (MAU) forms.
    line = re.sub(r"(?i)m[aâãàáảạăắằặẳẵ]u\s*(?:s[oố])?\s*[bB][\s\d\-/\w]*.*", "", line)
    line = re.sub(r"(?i)\bm[aâãàáảạăắằặẳẵ]u\b.*", "", line)        # bare 'MÃU' / 'MAU' residual
    line = re.sub(r"(?i)\b[bB]\s*0\d[-/\w]+.*", "", line)          # e.g. B01-DN/HN standalone
    line = re.sub(r"(?i)\bban\s+hành\b.*", "", line)
    line = re.sub(r"(?i)===\s*PAGE.*", "", line)

    # 4. Address / location noise (common in company headers)
    #    e.g. 'Lô CN11+CN12, cụm công nghiệp An Đồng,'
    #         'thị trấn Nam Sách, huyện Nam Sách, tỉnh Hải Dương'
    line = re.sub(r"(?i)\b(?:lô|cụm\s+công\s+nghiệp|thị\s+trấn|huyện|tỉnh|phường|quận|thành\s+phố)\b.*", "", line)

    # Clean up dangling punctuation & outer whitespace
    line = line.strip()
    line = re.sub(r"^[-–—\s,\.:;()\[\]]+|[-–—\s,\.:;()\[\]]+$", "", line)
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
        if not cleaned or _FULL_LINE_NOISE.match(cleaned) or len(cleaned) > 120 or _TEMPLATE_CODE_RE.search(cleaned):
            continue

        if _PAREN_RE.match(cleaned):
            suffixes.append(cleaned)
            continue

        # Found the valid line — also grab the cleaned line above if meaningful
        parts: List[str] = []
        if i > 0:
            prev_line = lines[i - 1]
            cleaned_prev = clean_line_noise(prev_line)
            
            # Heading prefix checks
            starts_with_heading_prefix = bool(
                re.match(r"^(?:\d+\.|[I-VX]+\.|[A-H]\.|[a-z]\))", cleaned)
            )
            
            prev_ends_with_punctuation = bool(
                cleaned_prev.endswith(".") or cleaned_prev.endswith(":") or cleaned_prev.endswith("?") or cleaned_prev.endswith("!")
            )
            
            is_valid_prev = (
                cleaned_prev 
                and not _FULL_LINE_NOISE.match(cleaned_prev) 
                and not _PAREN_RE.match(cleaned_prev)
                and not starts_with_heading_prefix
                and not prev_ends_with_punctuation
                and len(cleaned_prev) <= 80
                and not _TEMPLATE_CODE_RE.search(cleaned_prev)
            )
            
            if is_valid_prev:
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
    raw_content: str,
) -> Generator[Tuple[int, Tag, str, str, str, int], None, None]:
    """
    Parse all <table> tags from raw text using BeautifulSoup + lxml.
    NOTE: Regex is NOT used to parse HTML (project rule).

    Yields:
        idx          -- sequential table index within the file
        table_tag    -- BeautifulSoup Tag object
        pre_text     -- raw context lines above the table (for debugging)
        table_name   -- extracted heading string
        unit         -- extracted monetary unit string
        source_line  -- 1-indexed line number in the original source file
    """
    # Pre-compute 1-indexed source line numbers for every <table> tag by
    # scanning raw_content (before <br> injection) for literal '<table'
    # occurrences and counting newlines before each hit.
    # This avoids relying on lxml .sourceline, which is unreliable after
    # BeautifulSoup wraps the fragment in implicit <html>/<body> elements.
    raw_lower   = raw_content.lower()
    raw_lines   = raw_content.splitlines()   # 0-indexed list for context lookup
    table_source_lines: List[int] = []
    search_start = 0
    while True:
        pos = raw_lower.find("<table", search_start)
        if pos == -1:
            break
        line_num = raw_content[:pos].count("\n") + 1  # 1-indexed
        table_source_lines.append(line_num)
        search_start = pos + 1

    soup = BeautifulSoup(content, "lxml")
    for idx, table_tag in enumerate(soup.find_all("table")):
        source_line = table_source_lines[idx] if idx < len(table_source_lines) else 0
        orig_line_0 = max(0, source_line - 1)   # convert to 0-indexed

        pre_text   = _get_preceding_lines_from_raw(raw_lines, orig_line_0, n=15)
        table_name = extract_table_name(pre_text)
        unit       = extract_unit(pre_text)
        yield idx, table_tag, pre_text, table_name, unit, source_line



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


# ---------------------------------------------------------------------------
_HEADER_RES: List[re.Pattern] = [
    re.compile(r"\b(stt|mã\s+số|ma\s+so|thuyết\s+minh|thuyet\s+minh|chỉ\s+tiêu|chi\s+tieu|khoản\s+mục|khoan\s+muc)\b", re.IGNORECASE),
    re.compile(r"\b(tài\s+sản|tai\s+san|nguồn\s+vốn|nguon\s+von|doanh\s+thu|chi\s+phí|chi\s+phi|vốn\s+góp|vốn\s+điều\s+lệ|cổ\s+phần|cổ\s+phiếu|lợi\s+nhuận|quỹ|thặng\s+dư)\b", re.IGNORECASE),
    re.compile(r"\b(năm|quý|quy)\s+\d{4}\b", re.IGNORECASE),
    re.compile(r"\b(31/12|01/01|30/06|30/09)\b"),
    re.compile(r"^\b(20\d{2}|19\d{2})\b$"),
    re.compile(r"\b(số\s+cuối|số\s+đầu|năm\s+nay|năm\s+trước|kỳ\s+này|kỳ\s+trước|giá\s+gốc|dự\s+phòng)\b", re.IGNORECASE),
    re.compile(r"\b(giá\s+trị|gia\s+tri|tăng|tang|giảm|giam|cộng|cong|tổng|tong|nội\s+dung|noi\s+dung|loại|loai|tiền|tien|đầu\s+năm|cuối\s+năm|đầu\s+kỳ|cuối\s+kỳ|lãi\s+suất|lai\s+suat|đáo\s+hạn|dao\s+han|bảo\s+đảm|bao\s+dam)\b", re.IGNORECASE),
    re.compile(r"\b(năm|nam|ngày|ngay|tháng|thang|quý|quy)\b", re.IGNORECASE),
]

_SECTION_LETTER_RE: re.Pattern = re.compile(
    r"^(?!(?:P|Q|T|H|X|K|S|ĐT|ĐC)\.)[A-Z]\.\s*.*"  # Case-sensitive
)
_SECTION_OTHER_RE: re.Pattern = re.compile(
    r"^(?:"
    r"[I|V|X]+\.\s*.*|"                                # Roman numerals: I., II., III.
    r"(?:[a-z\d]+\)?[.\s]*)?(?:Doanh thu|Mua hàng|Vay|Phải thu.*|Phải trả.*|Trả trước.*|Đầu tư vào.*)" # Phân mục lớn
    r")$",
    re.IGNORECASE                                      # Case-insensitive
)

_FINANCIAL_AMOUNT_RE: re.Pattern = re.compile(r"^\(?-?\d{1,3}(?:\.\d{3})+(?:,\d+)?\)?$|^\(?-?\d{4,}\)?$")

def check_is_financial_amount(val: Any) -> bool:
    """Check if a cell value matches the financial amount pattern, stripping optional footnote suffixes like (*), (1), (i)."""
    if pd.isna(val) or val is None:
        return False
    val_str = str(val).strip().replace(" ", "")
    if not val_str:
        return False
    # Strip footnote suffix like (*), (1), (i), (a) from the end
    val_cleaned = re.sub(r"\(\*?\w*\)$", "", val_str)
    return bool(_FINANCIAL_AMOUNT_RE.match(val_cleaned))

_TEMPLATE_CODE_RE: re.Pattern = re.compile(
    r"\b(?:mẫu|mâu|biểu|form|biêu)\s*số?\s*[a-z]?\s*\d+[-–/\w]*\b|\b[b]\s*\d{2,}[-–/\w]*\b", 
    re.IGNORECASE
)

_COMMON_LABELS: Set[str] = {
    "chỉ tiêu", "chi tieu", "tài sản", "tai san", "nguồn vốn", "nguon von", 
    "stt", "mã số", "ma so", "khoản mục", "khoan muc", "nội dung", "noi dung",
    "mã", "ma", "thuyết minh", "thuyet minh", "tên công ty", "tên", "đối tượng"
}

def is_valid_header_row(row: pd.Series) -> bool:
    """
    Check if a row is a valid header row.
    Requirements:
    - Entire row must be text/dates (no numeric financial amounts).
    - Non-empty values must NOT be all identical (e.g. not all NaN or all same string).
    - Must contain at least one text/header keyword.
    """
    non_empty_vals = []
    has_numeric = False
    has_header_kw = False
    
    for val in row.values:
        if pd.isna(val):
            continue
        val_str = str(val).strip()
        if not val_str:
            continue
        
        # Clean currency suffix before checking keyword to handle 'Năm 2015VND' -> 'Năm 2015'
        val_cleaned = clean_header_value(val)
        
        if check_is_financial_amount(val):
            cleaned = val_str.replace(" ", "").replace("(", "").replace(")", "")
            if not (cleaned.isdigit() and len(cleaned) < 3):
                has_numeric = True
                
        non_empty_vals.append(val_cleaned.lower())
        if any(rx.search(val_cleaned) for rx in _HEADER_RES):
            has_header_kw = True
            
    if has_numeric:
        return False
        
    if not non_empty_vals:
        return False
        
    if len(set(non_empty_vals)) == 1:
        return False
        
    return has_header_kw


def is_header_extension_row(row: pd.Series) -> Tuple[bool, Optional[str]]:
    """
    Check if a row is a header extension/unit row.
    Sign: Non-empty values are all identical (e.g., all 'VND' or 'Triệu đồng'), and some cells may be empty.
    """
    non_empty_vals = []
    for val in row.values:
        if pd.isna(val):
            continue
        val_str = str(val).strip()
        if val_str:
            non_empty_vals.append(val_str)
            
    if len(non_empty_vals) > 0 and len(set(non_empty_vals)) == 1:
        common_val = non_empty_vals[0]
        if any(u in common_val.lower() for u in ["đợt", "tháng"]) and len(common_val) > 15:
            return False, None
        return True, common_val
    return False, None


def has_numeric_data_columns(df: pd.DataFrame) -> bool:
    """Check if a DataFrame has at least one column containing numeric financial amounts."""
    meta_cols = {"Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "Nam_Tai_Chinh", "Loai_Bao_Cao", "Ten_Bang", "Don_Vi_Tinh", "Tep_Nguon"}
    data_cols = [c for c in df.columns if c not in meta_cols]
    if not data_cols:
        return False
        
    for col in data_cols:
        for val in df[col].dropna().values:
            if check_is_financial_amount(val):
                return True
    return False


def is_header_row(row: pd.Series) -> bool:
    """Check if a row is a table header row based on financial header keywords, excluding financial amount rows."""
    return is_valid_header_row(row)


def is_currency_row(row: pd.Series) -> bool:
    """Check if a row contains only currency units or empty cells."""
    is_ext, _ = is_header_extension_row(row)
    return is_ext


def is_descriptor_row(row: pd.Series) -> bool:
    """Check if a row contains description text without financial numbers."""
    has_text = False
    for val in row.values:
        if pd.isna(val):
            continue
        val_str = str(val).strip()
        if not val_str:
            continue
        if check_is_financial_amount(val):
            return False
        cleaned = val_str.replace(" ", "").replace("(", "").replace(")", "")
        if cleaned.isdigit() and len(cleaned) < 3:
            continue
        has_text = True
    return has_text

def is_date_only_row(row: pd.Series) -> bool:
    """Check if all non-empty cells in the row are date/year labels."""
    has_val = False
    date_patterns = re.compile(
        r"^(?:31/12|01/01|30/06|30/09|\d{1,2}/\d{1,2}/\d{4}|\d{4}|năm\s+\d{4}|tại\s+\d{1,2}/\d{1,2}/\d{4})$", 
        re.IGNORECASE
    )
    for val in row.values:
        if pd.isna(val):
            continue
        val_str = str(val).strip()
        if not val_str:
            continue
        has_val = True
        if not date_patterns.match(val_str) and val_str.lower() not in ["tại", "ngày", "năm"]:
            return False
    return has_val

def clean_header_value(val: Any) -> str:
    """Strip currency suffixes from column name strings."""
    if pd.isna(val) or val is None:
        return ""
    val_str = str(val).strip()
    cleaned = re.sub(r"\s*(?:VND|VÐ|VĐ|USD|đđ|đ|đồng|Đồng)\b.*", "", val_str, flags=re.IGNORECASE)
    return cleaned.strip()

def _extract_headers_smart_internal(df: pd.DataFrame) -> Tuple[List[str], int, Optional[str]]:
    """Determine best headers from top rows, number of rows to drop, and optional unit."""
    if df.empty:
        return list(df.columns), 0, None

    num_rows = len(df)
    row0 = df.iloc[0]
    
    row0_valid = is_valid_header_row(row0)
    
    if row0_valid:
        if num_rows > 1:
            row1 = df.iloc[1]
            is_ext, ext_val = is_header_extension_row(row1)
            if is_ext:
                header_cols = [clean_header_value(v) for v in row0.values]
                header_cols = [name if name else f"Cột_{i}" for i, name in enumerate(header_cols)]
                header_cols = make_columns_unique(header_cols)
                return header_cols, 2, ext_val
            elif is_date_only_row(row1):
                header_cols = [clean_header_value(v) for v in row0.values]
                header_cols = [name if name else f"Cột_{i}" for i, name in enumerate(header_cols)]
                header_cols = make_columns_unique(header_cols)
                return header_cols, 2, None
            elif is_date_only_row(row0) and is_valid_header_row(row1):
                header_cols = [clean_header_value(v) for v in row1.values]
                header_cols = [name if name else f"Cột_{i}" for i, name in enumerate(header_cols)]
                header_cols = make_columns_unique(header_cols)
                return header_cols, 2, None
            elif is_valid_header_row(row1):
                if num_rows > 2:
                    row2 = df.iloc[2]
                    is_ext2, ext_val2 = is_header_extension_row(row2)
                    if is_ext2:
                           header_cols = [clean_header_value(v) for v in row1.values]
                           header_cols = [name if name else f"Cột_{i}" for i, name in enumerate(header_cols)]
                           header_cols = make_columns_unique(header_cols)
                           return header_cols, 3, ext_val2
                    elif is_date_only_row(row2):
                           header_cols = [clean_header_value(v) for v in row1.values]
                           header_cols = [name if name else f"Cột_{i}" for i, name in enumerate(header_cols)]
                           header_cols = make_columns_unique(header_cols)
                           return header_cols, 3, None
                
                header_cols = [clean_header_value(v) for v in row1.values]
                header_cols = [name if name else f"Cột_{i}" for i, name in enumerate(header_cols)]
                header_cols = make_columns_unique(header_cols)
                return header_cols, 2, None

        header_cols = [clean_header_value(v) for v in row0.values]
        header_cols = [name if name else f"Cột_{i}" for i, name in enumerate(header_cols)]
        header_cols = make_columns_unique(header_cols)
        return header_cols, 1, None

    if num_rows > 1 and is_valid_header_row(df.iloc[1]):
        header_cols = [clean_header_value(v) for v in df.iloc[1].values]
        header_cols = [name if name else f"Cột_{i}" for i, name in enumerate(header_cols)]
        header_cols = make_columns_unique(header_cols)
        return header_cols, 2, None

    header_cols = [f"Cột_{i}" for i in range(len(df.columns))]
    return header_cols, 0, None


def extract_headers_smart(df: pd.DataFrame) -> Tuple[List[str], int, Optional[str]]:
    """Determine best headers from top rows, number of rows to drop, and optional unit (post-processing wrapper)."""
    cols, drop_n, unit = _extract_headers_smart_internal(df)
    if cols:
        first_val = str(cols[0]).strip()
        date_patterns = re.compile(
            r"\b(?:\d{1,2}/\d{1,2}/\d{4}|\d{4}|năm\s+\d{4}|31/12|01/01|30/06|30/09|ngày\s+\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4})\b", 
            re.IGNORECASE
        )
        if date_patterns.search(first_val) or first_val.lower() in ["tại", "ngày", "năm"]:
            cols[0] = "Chỉ tiêu"
            cols = make_columns_unique(cols)
    return cols, drop_n, unit


def is_section_header_row(row: pd.Series) -> bool:
    """Check if a row is a section header (sub-table boundary)."""
    text_values = []
    has_numeric = False
    for val in row.values:
        if pd.isna(val):
            continue
        val_str = str(val).strip()
        if not val_str:
            continue
        cleaned_num = val_str.replace(".", "").replace(",", "").replace("-", "").replace("(", "").replace(")", "").strip()
        if cleaned_num.isdigit() and len(cleaned_num) > 0:
            has_numeric = True
        else:
            text_values.append(val_str)

    if not text_values:
        return False

    unique_text = list(dict.fromkeys(text_values))
    combined_text = " ".join(unique_text).strip()
    if _SECTION_LETTER_RE.match(combined_text) or _SECTION_OTHER_RE.match(combined_text):
        return True

    if not has_numeric:
        for t in unique_text:
            if _SECTION_LETTER_RE.match(t) or _SECTION_OTHER_RE.match(t):
                return True

    return False

def _has_numeric_amounts(row: pd.Series) -> bool:
    """Check if a row contains numeric financial amount cells."""
    for val in row.values:
        if check_is_financial_amount(val):
            return True
    return False


def ensure_subtable_totals(df: pd.DataFrame) -> pd.DataFrame:
    """
    If a sub-table has multiple data rows and no explicit summary row at the end,
    either copy section total amounts from the first row or compute column totals,
    and append a standardized 'TỔNG CỘNG' row at the bottom.
    """
    if len(df) <= 1:
        return df

    last_row_text = " ".join([str(val).lower() for val in df.iloc[-1].values if not pd.isna(val)])
    summary_keywords = ["tổng cộng", "cộng", "lưu chuyển tiền thuần", "tổng các khoản"]
    if any(kw in last_row_text for kw in summary_keywords):
        return df

    first_row = df.iloc[0]
    if _has_numeric_amounts(first_row):
        total_row = first_row.copy()
        for c_idx in range(len(total_row)):
            val = total_row.iloc[c_idx]
            if not pd.isna(val):
                val_str = str(val).strip()
                cleaned = val_str.replace(" ", "").replace(".", "").replace(",", "").replace("-", "")
                if val_str and not _FINANCIAL_AMOUNT_RE.match(val_str.replace(" ", "")) and not cleaned.isdigit():
                    total_row.iloc[c_idx] = "TỔNG CỘNG"
                    break
        total_df = pd.DataFrame([total_row.to_dict()])
        return pd.concat([df, total_df], ignore_index=True)

    first_row_text = " ".join([str(val).lower() for val in first_row.values if not pd.isna(val)])
    if any(kw in first_row_text for kw in summary_keywords):
        return df

    cols = list(df.columns)
    total_row = {}
    has_summed = False

    for c_idx in range(len(cols)):
        col_name = cols[c_idx]
        series = df.iloc[:, c_idx]
        values = series.dropna().tolist()
        numeric_vals = []
        for v in values:
            v_str = str(v).strip().replace(".", "").replace(",", "")
            if v_str.startswith("(") and v_str.endswith(")"):
                v_str = "-" + v_str[1:-1]
            try:
                num = float(v_str)
                numeric_vals.append(num)
            except ValueError:
                pass

        if len(numeric_vals) == len(values) and len(values) > 0:
            total_val = sum(numeric_vals)
            if total_val.is_integer():
                total_row[col_name] = f"{int(total_val):,}".replace(",", ".")
            else:
                total_row[col_name] = f"{total_val:,.2f}".replace(",", ".")
            has_summed = True
        else:
            total_row[col_name] = "TỔNG CỘNG" if not has_summed and c_idx == 0 else ""

    if has_summed:
        total_df = pd.DataFrame([total_row])
        df = pd.concat([df, total_df], ignore_index=True)

    return df


def clean_subtable_df(sub_df: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[str]]:
    """Clean repeating headers, dates, and currency rows from a subtable DataFrame."""
    if sub_df.empty:
        return sub_df, None
        
    sub_unit = None
    # 1. Clean headers/currencies from the top of the subtable
    while len(sub_df) > 0:
        first_row = sub_df.iloc[0]
        if is_currency_row(first_row):
            sub_unit = "VND"
            sub_df = sub_df.iloc[1:].copy()
        elif is_date_only_row(first_row):
            sub_df = sub_df.iloc[1:].copy()
        else:
            break
            
    # 2. Clean repeating headers/currencies from the body of the subtable
    body_rows_to_keep = []
    for r_idx in range(len(sub_df)):
        row_series = sub_df.iloc[r_idx]
        if is_currency_row(row_series) or is_date_only_row(row_series):
            if is_currency_row(row_series):
                sub_unit = "VND"
            continue
        body_rows_to_keep.append(r_idx)
    sub_df = sub_df.iloc[body_rows_to_keep].copy()
    
    return sub_df, sub_unit


def split_dataframe_into_subtables(
    df: pd.DataFrame, 
    parent_table_name: str
) -> List[Tuple[str, pd.DataFrame, Optional[str]]]:
    """
    Split a DataFrame into sub-tables based on section header rows.
    Returns list of (sub_table_name, sub_df, sub_unit).
    """
    if df.empty:
        return [(parent_table_name, df, None)]

    split_indices = []
    section_names = []

    for row_idx in range(len(df)):
        r = df.iloc[row_idx]
        if is_section_header_row(r):
            text_cells = [
                str(val).strip() for val in r.values
                if not pd.isna(val) and str(val).strip() and not str(val).strip().replace(".", "").replace(",", "").replace("-", "").replace("(", "").replace(")", "").isdigit()
            ]
            sec_name = " ".join(dict.fromkeys(text_cells)).strip()
            if sec_name:
                split_indices.append(row_idx)
                section_names.append(sec_name)

    if not split_indices:
        sub_df, sub_unit = clean_subtable_df(df)
        return [(parent_table_name, sub_df, sub_unit)]

    subtables: List[Tuple[str, pd.DataFrame, Optional[str]]] = []
    for s_idx in range(len(split_indices)):
        start_i = split_indices[s_idx]
        end_i = split_indices[s_idx + 1] if s_idx + 1 < len(split_indices) else len(df)
        sub_df = df.iloc[start_i:end_i].copy()
        if sub_df.empty:
            continue

        sec_title = section_names[s_idx]
        sub_table_name = f"{parent_table_name}_{sec_title}" if parent_table_name else sec_title
        
        # Clean headers from subtable body
        if len(sub_df) > 0:
            sub_df = sub_df.iloc[1:].copy()
            
        sub_df, sub_unit = clean_subtable_df(sub_df)
                
        if sub_df.empty:
            continue
            
        sub_df = ensure_subtable_totals(sub_df)
        subtables.append((sub_table_name, sub_df, sub_unit))

    return subtables if subtables else [(parent_table_name, df, None)]


def make_columns_unique(cols: List[str]) -> List[str]:
    """Ensure all column names in cols are unique by appending _1, _2 to duplicates."""
    seen: Dict[str, int] = {}
    unique_cols = []
    for c in cols:
        name = str(c).strip()
        if name not in seen:
            seen[name] = 0
            unique_cols.append(name)
        else:
            seen[name] += 1
            unique_cols.append(f"{name}_{seen[name]}")
    return unique_cols


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
        raw_content = file_path.read_text(encoding="utf-8", errors="replace")
        # Keep raw_content (before <br> injection) for line-number tracking
        # and context-window extraction.  Normalise line endings first.
        raw_content = raw_content.replace("\r\n", "\n").replace("\r", "\n")

        # Insert <br> before each newline so BeautifulSoup preserves line
        # breaks.  The number of \n characters is unchanged by this step,
        # which is why counting \n in raw_content gives correct line numbers.
        content = raw_content.replace("\n", "<br>\n")
    except OSError as exc:
        logger.error("Cannot read %s: %s", file_path, exc)
        return []

    tables: List[pd.DataFrame] = []
    last_header: Optional[Tuple[int, List[str]]] = None
    for idx, table_tag, _, table_name, unit, source_line in parse_tables_from_content(content, raw_content):
        raw_df = table_tag_to_dataframe(table_tag)
        if raw_df is None or raw_df.empty:
            continue

        num_cols = len(raw_df.columns)

        # Smart header extraction
        header_cols, drop_n, extracted_unit = extract_headers_smart(raw_df)

        if drop_n > 0:
            last_header = (num_cols, header_cols)
            df_cleaned = raw_df.iloc[drop_n:].copy()
            df_cleaned.columns = header_cols
        elif last_header is not None and last_header[0] == num_cols:
            header_cols = last_header[1]
            df_cleaned = raw_df.copy()
            df_cleaned.columns = header_cols
        else:
            last_header = None
            header_cols = make_columns_unique([f"Cột_{i}" for i in range(num_cols)])
            df_cleaned = raw_df.copy()
            df_cleaned.columns = header_cols

        # Update unit metadata if currency row was dropped and preceding text had no unit
        table_unit = unit if unit else (extracted_unit if extracted_unit else "")
        # Split into sub-tables if section headers exist
        subtables = split_dataframe_into_subtables(df_cleaned, table_name)

        for sub_idx, (sub_table_name, sub_df, sub_unit) in enumerate(subtables):
            # Include the original source line number so a result can be traced
            # back to the exact location in the .txt file (Issue 2 fix).
            source_ref = f"{file_path.as_posix()}#table_{idx}_{sub_idx}@line_{source_line}"
            final_unit = sub_unit if sub_unit else table_unit
            enriched_df = attach_metadata(
                sub_df, ticker, company_name, year,
                report_type, sub_table_name, final_unit, source_ref
            )
            # Only keep tables that contain numeric data columns
            if has_numeric_data_columns(enriched_df):
                tables.append(enriched_df)
            else:
                logger.info("Discarding text-only table/subtable: %s", sub_table_name)

    return tables
# ---------------------------------------------------------------------------
# 1E. Save CSVs
# ---------------------------------------------------------------------------

def build_csv_output_path(
    file_path: Path,
    statements_dir: Path,
    output_dir: Path,
    table_index: str | int,
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
                anchor_idx = df["Tep_Nguon"].iloc[0].split("#table_")[1]
            except (IndexError, ValueError):
                anchor_idx = "0"
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

    Includes up to 50 unique financial line item labels from the detected label column.
    """
    data_cols = [c for c in df.columns if c not in META_COLS]
    line_items: List[str] = []
    if data_cols:
        try:
            label_idx = 0
            label_keywords = ["chỉ tiêu", "chi tieu", "tài sản", "tai san", "nguồn vốn", "nguon von", "khoản mục", "khoan muc", "tên", "ten", "đối tượng", "doi tuong"]
            for idx_c, col in enumerate(data_cols):
                if any(kw in str(col).lower() for kw in label_keywords):
                    label_idx = idx_c
                    break
            else:
                stt_keywords = ["stt", "mã số", "ma so", "mã", "ma"]
                if len(data_cols) > 1 and any(kw in str(data_cols[0]).lower() for kw in stt_keywords):
                    label_idx = 1

            # Match position in original df.columns
            target_col_name = data_cols[label_idx]
            col_pos_in_df = list(df.columns).index(target_col_name)

            line_items = (
                df.iloc[:, col_pos_in_df].dropna().astype(str).str.strip()
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

