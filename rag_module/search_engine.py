"""
search_engine.py
================
ViFinQA Hybrid Search Engine — Qdrant (Dense) + BM25 (Sparse) + RRF fusion.

This module is designed to be imported directly in a Kaggle Notebook:

    import sys
    sys.path.append("/kaggle/input/your-dataset-name")
    from rag_module.search_engine import run_hybrid_search

    results = run_hybrid_search("Lợi nhuận sau thuế của FPT năm 2023")
    for r in results:
        print(r["Ten_Bang"], r["rrf_score"])

Resources (Qdrant client, embedding model, BM25 index, company map) are
loaded ONCE on the first call and cached globally for subsequent calls.

NOTE: Qdrant runs in LOCAL DISK MODE — QdrantClient(path=QDRANT_DB_PATH).
      No Docker, no server, no API key required.
"""

from __future__ import annotations

import os
import logging
import pickle
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    SearchParams,
    QuantizationSearchParams,
)
from sentence_transformers import SentenceTransformer

# =============================================================================
# CONFIGURATION
# =============================================================================

_HERE = Path(__file__).parent   # always points to the rag_module/ directory

# --- LOCAL paths (auto-detect root or test directory) ---
_DEFAULT_QDRANT = _HERE / "qdrant_local_db"
_TEST_QDRANT    = _HERE / "test" / "qdrant_local_db"
QDRANT_DB_PATH  = _DEFAULT_QDRANT if _DEFAULT_QDRANT.exists() else _TEST_QDRANT

_DEFAULT_BM25   = _HERE / "bm25_index.pkl"
_TEST_BM25      = _HERE / "test" / "bm25_index.pkl"
BM25_PATH       = _DEFAULT_BM25 if _DEFAULT_BM25.exists() else _TEST_BM25

_DEFAULT_CSV = _HERE / "ViFinQA" / "code_stock.csv"
CODE_STOCK_CSV = _DEFAULT_CSV if _DEFAULT_CSV.exists() else _HERE / "code_stock.csv"

# --- KAGGLE paths (auto-detect Kaggle dataset path) ---
_KAGGLE_DATA_DIR = Path("/kaggle/input/r2-ai-output/r2AI_data")
if (_KAGGLE_DATA_DIR / "qdrant_local_db").exists():
    QDRANT_DB_PATH = _KAGGLE_DATA_DIR / "qdrant_local_db"
if (_KAGGLE_DATA_DIR / "bm25_index.pkl").exists():
    BM25_PATH = _KAGGLE_DATA_DIR / "bm25_index.pkl"
if (_KAGGLE_DATA_DIR / "code_stock.csv").exists():
    CODE_STOCK_CSV = _KAGGLE_DATA_DIR / "code_stock.csv"

COLLECTION_NAME      = "financial_tables"
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_TOP_K        = 10
RRF_K                = 60    # Reciprocal Rank Fusion smoothing constant

# =============================================================================
# Logging
# =============================================================================

def _configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

logger = logging.getLogger("search_engine")

# =============================================================================
# Type aliases
# =============================================================================

SearchResult = Dict[str, Any]
RRFResult    = Dict[str, Any]

# =============================================================================
# Resource loaders (called once; results cached in module-level globals)
# =============================================================================

_qdrant_client:  Optional[QdrantClient]         = None
_embed_model:    Optional[SentenceTransformer]   = None
_bm25_index:     Optional[Any]                   = None
_doc_mapping:    Optional[List[Dict[str, Any]]]  = None
_company_map:    Optional[List[Tuple[str, str]]] = None


def load_qdrant_client(db_path: Path = QDRANT_DB_PATH) -> QdrantClient:
    """
    Create a QdrantClient in LOCAL DISK MODE.
    No Docker / server required — data is read directly from db_path.
    If the directory is read-only (common in Kaggle mounts), it will copy
    the DB to a writable location (e.g. /tmp) and open it from there.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"Qdrant DB not found: {db_path}\n"
            "Run data_pipeline.py first to build the index."
        )

    # Check if we can write to the directory (Qdrant needs to write a .lock file)
    test_path = db_path
    try:
        lock_file = db_path / ".lock_test"
        with open(lock_file, "w") as f:
            f.write("test")
        lock_file.unlink()
    except Exception:
        # If writing fails (e.g. Read-only file system on Kaggle), copy to /tmp
        import shutil
        import tempfile
        import os
        
        # Use a unique name for the temporary directory
        writable_dir = Path(tempfile.gettempdir()) / f"qdrant_db_{db_path.name}"
        logger.warning(
            "Directory %s is read-only. Copying database to writable location: %s",
            db_path, writable_dir
        )
        
        if writable_dir.exists():
            try:
                shutil.rmtree(writable_dir)
            except Exception:
                pass
                
        shutil.copytree(db_path, writable_dir)
        
        # Ensure files and directories are writable
        for root, dirs, files in os.walk(writable_dir):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o777)
                except Exception:
                    pass
            for f in files:
                try:
                    os.chmod(os.path.join(root, f), 0o666)
                except Exception:
                    pass
        try:
            os.chmod(writable_dir, 0o777)
        except Exception:
            pass
            
        test_path = writable_dir

    logger.info("Opening Qdrant local DB: %s", test_path)
    return QdrantClient(path=str(test_path))


def load_embedding_model(model_name: str = EMBEDDING_MODEL_NAME) -> SentenceTransformer:
    """Load (and cache) the SentenceTransformer embedding model."""
    logger.info("Loading embedding model: %s", model_name)
    model = SentenceTransformer(model_name)
    return model


def load_bm25_index(pkl_path: Path = BM25_PATH) -> Tuple[Any, List[Dict[str, Any]]]:
    """Load BM25Okapi and doc_mapping from the pickle file."""
    if not pkl_path.is_file():
        logger.warning(f"BM25 index not found: {pkl_path}")
        return None, []

    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
        bm25        = data["bm25"]
        doc_mapping = data["doc_mapping"]
        logger.info("BM25 index loaded. Corpus size: %d documents.", getattr(bm25, 'corpus_size', len(doc_mapping)))
        return bm25, doc_mapping
    except MemoryError:
        logger.warning("MemoryError while loading BM25 index pickle file (%s). Falling back to Qdrant Dense Search only.", pkl_path)
        return None, []
    except Exception as e:
        logger.warning("Failed to load BM25 index: %s. Falling back to Qdrant Dense Search only.", e)
        return None, []


def load_company_map(csv_path: Path = CODE_STOCK_CSV) -> List[Tuple[str, str]]:
    """
    Load code_stock.csv -> list of (company_name, ticker) sorted by name
    length DESCENDING so longest-match wins during entity extraction.
    """
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
        ticker_col = next((c for c in df.columns if "CK" in c.upper()), df.columns[0])
        name_col   = next((c for c in df.columns if "TÊN" in c.upper() or "TEN" in c.upper()),
                          df.columns[1])
        pairs = [
            (str(row[name_col]).strip(), str(row[ticker_col]).strip())
            for _, row in df.iterrows()
            if str(row[ticker_col]).strip() and str(row[name_col]).strip()
        ]
        return sorted(pairs, key=lambda x: len(x[0]), reverse=True)
    except Exception as exc:
        logger.warning("Could not load company map from %s: %s", csv_path, exc)
        return []


def _ensure_resources() -> None:
    """Lazy-load all resources on first call (cached in module globals)."""
    global _qdrant_client, _embed_model, _bm25_index, _doc_mapping, _company_map
    if _qdrant_client is None:
        _qdrant_client = load_qdrant_client()
    if _embed_model is None:
        _embed_model = load_embedding_model()
    if _bm25_index is None:
        _bm25_index, _doc_mapping = load_bm25_index()
    if _company_map is None:
        _company_map = load_company_map()

# =============================================================================
# Query parsing
# =============================================================================

_YEAR_RE         = re.compile(r"\b(20\d{2})\b")
_CONSOLIDATED_RE = re.compile(r"hợp\s+nhất", re.IGNORECASE)
_TOKEN_SPLIT     = re.compile(r"[\s\.,;:()\[\]{}/\\\"'!?]+")


def parse_query(
    question: str,
    company_map: List[Tuple[str, str]],
) -> Tuple[str, str, str]:
    """
    Extract (ticker, year, report_type) from a Vietnamese question.

    Uses LONGEST-MATCH company name lookup to avoid ambiguity
    (e.g. 'CTCP Chứng khoán FPT' -> FTS, not FPT).
    Falls back to parenthesised ticker codes like (VJC).
    """
    q_lower = question.lower()

    # --- Ticker via longest company name match ---
    ticker = ""
    expanded_company_map = []
    for company_name, code in company_map:
        expanded_company_map.append((company_name, code))
        clean_name = re.sub(r"\b(CTCP|Tập đoàn|Công ty|Cổ phần|Ngân hàng|TMCP|\-\s*CTCP)\b", "", company_name, flags=re.IGNORECASE).strip(" -")
        if clean_name and clean_name.lower() != company_name.lower() and len(clean_name) >= 3:
            expanded_company_map.append((clean_name, code))

    expanded_company_map.sort(key=lambda x: len(x[0]), reverse=True)

    for company_name, code in expanded_company_map:
        if company_name.lower() in q_lower:
            ticker = code
            break

    # Fallback: parenthesised ticker e.g. "(VCB)" or "(VIC)"
    if not ticker:
        m = re.search(r"\(([A-Z]{2,5})\)", question)
        if m:
            ticker = m.group(1)

    # Fallback: direct ticker code match as word
    if not ticker:
        tickers = {code.upper() for _, code in company_map}
        for w in re.findall(r"\b[A-Za-z]{3,5}\b", question):
            w_upper = w.upper()
            if w_upper in tickers:
                ticker = w_upper
                break

    # --- Year ---
    m = _YEAR_RE.search(question)
    year = m.group(1) if m else ""

    # --- Report type ---
    report_type = "consolidated" if _CONSOLIDATED_RE.search(question) else "separate"

    return ticker, year, report_type


def tokenize(text: str) -> List[str]:
    """Tokenise Vietnamese text for BM25 (lowercase + split on punctuation)."""
    return [t for t in _TOKEN_SPLIT.split(text.lower()) if len(t) >= 2]

# =============================================================================
# Dense search (Qdrant)
# =============================================================================

def qdrant_search(
    client:      QdrantClient,
    model:       SentenceTransformer,
    query:       str,
    ticker:      str,
    year:        str,
    report_type: Optional[str] = None,
    collection:  str = COLLECTION_NAME,
    top_k:       int = DEFAULT_TOP_K,
) -> List[SearchResult]:
    """
    Dense semantic search via Qdrant with strict payload filtering.

    Filters: Ma_Doanh_Nghiep == ticker  AND  Nam_Tai_Chinh == year
    Optional: Loai_Bao_Cao IN (report_type, 'unknown')
    ('unknown' covers companies that publish only one consolidated report.)
    """
    query_vector = model.encode(
        query, normalize_embeddings=True, convert_to_numpy=True
    ).tolist()

    must = []
    if ticker:
        must.append(FieldCondition(key="Ma_Doanh_Nghiep", match=MatchValue(value=ticker)))
    if year:
        must.append(FieldCondition(key="Nam_Tai_Chinh", match=MatchValue(value=year)))
    if report_type:
        must.append(
            FieldCondition(key="Loai_Bao_Cao",
                           match=MatchAny(any=[report_type, "unknown"]))
        )

    response = client.query_points(
        collection_name=collection,
        query=query_vector,
        query_filter=Filter(must=must),
        limit=top_k,
        with_payload=True,
        search_params=SearchParams(
            quantization=QuantizationSearchParams(
                rescore=True,
                oversampling=2.0,
            )
        ),
    )

    results: List[SearchResult] = []
    for rank, hit in enumerate(response.points, start=1):
        payload = hit.payload or {}
        results.append({"csv_path": payload.get("csv_path", ""),
                         "rank": rank, "score": hit.score, **payload})
    return results


# =============================================================================
# Sparse search (BM25)
# =============================================================================

def bm25_search(
    bm25:        Any,
    doc_mapping: List[Dict[str, Any]],
    query:       str,
    ticker:      str,
    year:        str,
    report_type: Optional[str] = None,
    top_k:       int = DEFAULT_TOP_K,
) -> List[SearchResult]:
    """
    Sparse BM25 search with strict metadata filtering.

    Filters: Ma_Doanh_Nghiep == ticker  AND  Nam_Tai_Chinh == year
    Optional: Loai_Bao_Cao IN (report_type, 'unknown')
    """
    if bm25 is None or not doc_mapping:
        return []

    tokens     = tokenize(query)
    all_scores = bm25.get_scores(tokens)
    ranked_idx = sorted(range(len(all_scores)),
                        key=lambda i: all_scores[i], reverse=True)

    results: List[SearchResult] = []
    rank_counter = 1
    for doc_idx in ranked_idx:
        if rank_counter > top_k:
            break
        meta = doc_mapping[doc_idx]
        if ticker and meta.get("Ma_Doanh_Nghiep", "").strip() != ticker.strip():
            continue
        if year and str(meta.get("Nam_Tai_Chinh", "")).strip() != str(year).strip():
            continue
        if report_type:
            val = meta.get("Loai_Bao_Cao", "").strip()
            if val not in (report_type.strip(), "unknown"):
                continue
        results.append({
            "csv_path": meta.get("csv_path", ""),
            "rank":     rank_counter,
            "score":    float(all_scores[doc_idx]),
            **meta,
        })
        rank_counter += 1
    return results


# =============================================================================
# Reciprocal Rank Fusion
# =============================================================================

def apply_rrf(
    dense:  List[SearchResult],
    sparse: List[SearchResult],
    k:      int = RRF_K,
) -> List[RRFResult]:
    """Merge dense + sparse ranked lists using RRF: score = 1/(k+rank)."""
    fusion: Dict[str, Dict[str, Any]] = {}

    def _add(results: List[SearchResult], rank_key: str) -> None:
        for hit in results:
            path = hit.get("csv_path", "")
            if not path:
                continue
            if path not in fusion:
                fusion[path] = {
                    "csv_path": path, "rrf_score": 0.0,
                    "dense_rank": None, "sparse_rank": None,
                    "_meta": {kk: vv for kk, vv in hit.items()
                              if kk not in ("rank", "score", "csv_path")},
                }
            fusion[path]["rrf_score"] += 1.0 / (k + hit["rank"])
            fusion[path][rank_key]     = hit["rank"]

    _add(dense,  "dense_rank")
    _add(sparse, "sparse_rank")

    return sorted(
        [{"csv_path": e["csv_path"], "rrf_score": round(e["rrf_score"], 6),
          "dense_rank": e["dense_rank"], "sparse_rank": e["sparse_rank"],
          **e["_meta"]}
         for e in fusion.values()],
        key=lambda x: x["rrf_score"], reverse=True,
    )


# =============================================================================
# Public API — run_hybrid_search
# =============================================================================

def run_hybrid_search(
    query:       str,
    top_k:       int           = DEFAULT_TOP_K,
    ticker:      Optional[str] = None,
    year:        Optional[str] = None,
    report_type: Optional[str] = None,
) -> List[RRFResult]:
    """
    High-level hybrid search function for use in Kaggle Notebooks.

    Automatically loads all resources on first call (cached thereafter).
    Auto-parses ticker, year, and report_type from the Vietnamese query
    if they are not provided explicitly.

    Args:
        query:       Vietnamese financial question.
        top_k:       Number of results to retrieve from each engine.
        ticker:      Override auto-parsed ticker (e.g. 'VCB').
        year:        Override auto-parsed year   (e.g. '2022').
        report_type: Override report type        ('separate' | 'consolidated').

    Returns:
        List of RRFResult dicts, sorted by rrf_score descending.
        Each dict contains: csv_path, rrf_score, dense_rank, sparse_rank,
        plus all metadata fields (Ten_Bang, Ma_Doanh_Nghiep, etc.).

    Example:
        results = run_hybrid_search("Lợi nhuận sau thuế của FPT năm 2023")
        for r in results[:3]:
            print(r['Ten_Bang'], r['rrf_score'])
    """
    _ensure_resources()

    # Parse query if not overridden
    if not ticker or not year:
        _t, _y, _rt = parse_query(query, _company_map)
        ticker      = ticker      or _t
        year        = year        or _y
        report_type = report_type or _rt

    if not ticker:
        logger.info("Ticker not explicitly found for query: '%s'. Performing broad hybrid search.", query)

    logger.info("Query: %s  |  Ticker: %s  |  Year: %s  |  Type: %s",
                query, ticker, year, report_type)

    dense  = qdrant_search(_qdrant_client, _embed_model, query,
                           ticker, year, report_type, COLLECTION_NAME, top_k)
    sparse = bm25_search(_bm25_index, _doc_mapping, query,
                          ticker, year, report_type, top_k)
    fused  = apply_rrf(dense, sparse, k=RRF_K)

    logger.info("Results: %d dense  |  %d sparse  |  %d fused",
                len(dense), len(sparse), len(fused))
    return fused


METADATA_HEADER_COLUMNS = {
    "Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "Nam_Tai_Chinh",
    "Loai_Bao_Cao", "Ten_Bang", "Don_Vi_Tinh", "Tep_Nguon"
}


def is_meaningful_text_column(series: pd.Series) -> bool:
    """Kiểm tra xem cột có chứa văn bản chỉ tiêu có nghĩa không (bỏ qua số thứ tự, mã số, ký tự mục)."""
    valid_vals = series.dropna().astype(str).str.strip()
    valid_vals = valid_vals[valid_vals != ""]
    if valid_vals.empty:
        return False

    meaningful_count = 0
    total = len(valid_vals)
    for val in valid_vals:
        # Nếu có từ/chuỗi dài hơn 4 ký tự hoặc chứa khoảng trắng không phải số thuần
        if len(val) > 4 or (" " in val and not val.replace(" ", "").isdigit()):
            meaningful_count += 1

    return (meaningful_count / total) >= 0.25 if total > 0 else False


def _resolve_local_csv_path(csv_path_str: str) -> Optional[Path]:
    """Resolve raw csv_path from index payload to an existing file path on local or Kaggle disk."""
    if not csv_path_str:
        return None
    p_str = csv_path_str.replace("\\", "/")
    direct = Path(p_str).resolve()
    if direct.exists():
        return direct

    idx_fin = p_str.find("ViFinQA")
    if idx_fin != -1:
        rel = p_str[idx_fin:]
        bases = [
            _HERE,
            _HERE.parent,
            Path.cwd(),
            Path("/kaggle/working/r2AI_2026"),
            Path("/kaggle/input/r2-ai-output/r2AI_data"),
            Path("/kaggle/input/r2-ai-output"),
        ]
        for base in bases:
            c1 = (base / rel).resolve()
            if c1.exists():
                return c1
            c2 = (base / "rag_module" / rel).resolve()
            if c2.exists():
                return c2
    return None


def get_first_meaningful_column(df: pd.DataFrame) -> Tuple[Optional[str], pd.Series]:
    """Tìm cột ĐẦU TIÊN CÓ NGHĨA trong DataFrame (bỏ qua metadata và các cột STT/Mã số thuần số)."""
    candidate_cols = [c for c in df.columns if c not in METADATA_HEADER_COLUMNS]
    if not candidate_cols:
        candidate_cols = list(df.columns)

    for col in candidate_cols:
        if is_meaningful_text_column(df[col]):
            return col, df[col]

    first_col = candidate_cols[0] if candidate_cols else df.columns[0]
    return first_col, df[first_col]


def search_by_company_and_content(
    company_name: str,
    content: str,
    year: Optional[str] = None,
    report_type: Optional[str] = None,
    top_k: Optional[int] = None,
) -> List[RRFResult]:
    """
    Tra cứu bảng báo cáo tài chính theo Hướng A (On-the-fly Hybrid Search trên Cột 0):
    1. Giới hạn/lọc toàn bộ danh sách bảng theo tên công ty (mã chứng khoán) & năm tài chính (không giới hạn số bảng).
    2. Rút ra tất cả các dòng chỉ tiêu ở CỘT ĐẦU TIÊN CÓ NGHĨA của TOÀN BỘ các bảng đã lọc (đọc toàn bộ dòng trong file CSV).
    3. Thực thi On-the-fly Hybrid Search (BM25 + SentenceTransformer Vector + RRF) trực tiếp trên tập dòng chỉ tiêu này.
    4. Xếp hạng các bảng dựa theo chỉ tiêu có điểm số cao nhất trong từng bảng.

    Args:
        company_name: Tên công ty hoặc mã chứng khoán (VD: 'Vinamilk', 'VNM', 'FPT')
        content: Nội dung/chỉ tiêu nằm ở cột đầu tiên có nghĩa (VD: 'Doanh thu thuần')
        year: Năm báo cáo tài chính (VD: '2023')
        report_type: Loại báo cáo ('separate' | 'consolidated')
        top_k: Số lượng bảng kết quả trả về (Nếu None hoặc <= 0, trả về TOÀN BỘ danh sách bảng đã xếp hạng).

    Returns:
        Danh sách các bảng kết quả tìm kiếm đã sắp xếp theo độ khớp.
    """
    _ensure_resources()
    from rank_bm25 import BM25Okapi
    import numpy as np

    # 1. Xác định ticker từ company_name
    ticker = ""
    if company_name:
        c_upper = company_name.strip().upper()
        if _company_map:
            tickers = {code.upper() for _, code in _company_map}
            if c_upper in tickers:
                ticker = c_upper

        if not ticker and _company_map:
            for c_name, code in _company_map:
                if c_name.lower() in company_name.lower() or company_name.lower() in c_name.lower():
                    ticker = code
                    break

        if not ticker and _company_map:
            t_parsed, _, _ = parse_query(company_name, _company_map)
            ticker = t_parsed

    logger.info("Direction A Search: Company='%s' (Ticker='%s') | Year=%s | Content='%s'",
                company_name, ticker, year, content)

    content_clean = content.strip() if content else ""
    content_lower = content_clean.lower()

    # 2. Lọc TOÀN BỘ danh sách bảng thuộc về (Ticker, Year)
    if ticker and _doc_mapping and content_clean:
        candidates = []
        for doc in _doc_mapping:
            if doc.get("Ma_Doanh_Nghiep", "").strip() != ticker:
                continue
            if year and str(doc.get("Nam_Tai_Chinh", "")).strip() != str(year):
                continue
            if report_type:
                val = doc.get("Loai_Bao_Cao", "").strip()
                if val not in (report_type, "unknown"):
                    continue
            candidates.append(doc)

        logger.info("Found %d candidate tables for ticker='%s', year='%s'", len(candidates), ticker, year)

        if candidates:
            # 3. Thu thập tất cả các dòng chỉ tiêu ở Cột đầu tiên từ TOÀN BỘ các bảng ứng viên
            row_items: List[Dict[str, Any]] = []
            for doc in candidates:
                raw_csv_path = doc.get("csv_path", "")
                csv_path_resolved = _resolve_local_csv_path(raw_csv_path)
                if csv_path_resolved and csv_path_resolved.exists():
                    try:
                        # Đọc TOÀN BỘ dòng trong file CSV thay vì giới hạn 100 dòng
                        df_sample = pd.read_csv(csv_path_resolved)
                        if not df_sample.empty:
                            col_name, col_series = get_first_meaningful_column(df_sample)
                            for r_idx, val in col_series.dropna().items():
                                val_str = str(val).strip()
                                if len(val_str) >= 2:
                                    row_items.append({
                                        "text": val_str,
                                        "col_name": str(col_name),
                                        "row_idx": r_idx,
                                        "doc": doc,
                                        "csv_path": str(csv_path_resolved),
                                    })
                    except Exception as exc:
                        logger.debug("Error reading CSV %s: %s", csv_path_resolved, exc)

            if row_items:
                logger.info("Collected %d line items from Column 0 across candidate tables. Running On-the-fly Hybrid Search...", len(row_items))

                # --- A. BM25 Search trên các dòng chỉ tiêu ---
                corpus_tokens = [tokenize(item["text"]) for item in row_items]
                bm25_model = BM25Okapi(corpus_tokens)
                query_tokens = tokenize(content_clean)
                bm25_scores = bm25_model.get_scores(query_tokens)
                sparse_ranked_indices = np.argsort(bm25_scores)[::-1]
                sparse_rank_map = {idx: rank + 1 for rank, idx in enumerate(sparse_ranked_indices)}

                # --- B. Dense Vector Search trên các dòng chỉ tiêu ---
                query_vec = _embed_model.encode(content_clean, normalize_embeddings=True, convert_to_numpy=True)
                line_texts = [item["text"] for item in row_items]
                line_vecs = _embed_model.encode(line_texts, batch_size=256, normalize_embeddings=True, convert_to_numpy=True)
                dense_scores = np.dot(line_vecs, query_vec)  # Cosine similarity
                dense_ranked_indices = np.argsort(dense_scores)[::-1]
                dense_rank_map = {idx: rank + 1 for rank, idx in enumerate(dense_ranked_indices)}

                # --- C. Reciprocal Rank Fusion (RRF) trên từng chỉ tiêu ---
                line_fusion: Dict[str, Dict[str, Any]] = {}
                for idx, item in enumerate(row_items):
                    csv_path = item["csv_path"]
                    d_rank = dense_rank_map[idx]
                    s_rank = sparse_rank_map[idx]
                    rrf = (1.0 / (RRF_K + d_rank)) + (1.0 / (RRF_K + s_rank))

                    # Cộng thưởng nếu chuỗi exact substring khớp (hoặc hàng nhãn chứa trong chuỗi truy vấn)
                    t_lower = item["text"].lower()
                    if content_lower in t_lower or (len(t_lower) >= 4 and t_lower in content_lower):
                        rrf += 0.1

                    # Mỗi bảng giữ chỉ tiêu có điểm RRF cao nhất
                    if csv_path not in line_fusion or rrf > line_fusion[csv_path]["rrf_score"]:
                        line_fusion[csv_path] = {
                            "csv_path": csv_path,
                            "rrf_score": round(rrf, 6),
                            "dense_rank": d_rank,
                            "sparse_rank": s_rank,
                            "content_matched": True,
                            "matched_col_name": item["col_name"],
                            "matched_sample": item["text"],
                            "matched_row_idx": item["row_idx"],
                            **item["doc"]
                        }

                fused_tables = sorted(line_fusion.values(), key=lambda x: x["rrf_score"], reverse=True)
                if fused_tables:
                    logger.info("Direction A Hybrid Search successfully ranked %d tables.", len(fused_tables))
                    if top_k is not None and top_k > 0:
                        return fused_tables[:top_k]
                    return fused_tables

    # 4. Fallback: Dùng standard Hybrid Search nếu không lọc được theo (Company, Year)
    logger.info("Fallback to standard Hybrid Search...")
    query = f"{company_name} {content}".strip() if company_name else content
    results = run_hybrid_search(
        query=query,
        top_k=top_k,
        ticker=ticker or None,
        year=year or None,
        report_type=report_type or None,
    )

    if not results and year:
        results = run_hybrid_search(
            query=query,
            top_k=top_k,
            ticker=ticker or None,
            year=None,
            report_type=report_type or None,
        )

    return results





# =============================================================================
# Targeted search helpers (team-requested additions)
# =============================================================================

def _resolve_ticker(company: str) -> str:
    """Resolve a company name or raw ticker string to a canonical ticker code.

    Uses the same longest-match company map as parse_query().
    Falls back to returning ``company`` uppercased if no match is found.
    """
    _ensure_resources()
    if not company:
        return ""
    if _company_map:
        c_upper = company.upper()
        all_tickers = {code for _, code in _company_map}
        if c_upper in all_tickers:
            return c_upper
        c_lower = company.lower()
        for name, code in _company_map:
            if name.lower() in c_lower or c_lower in name.lower():
                return code
    return company.upper()


def search_by_table_name(
    company: str,
    table_name_query: str,
    year: Optional[str] = None,
    report_type: Optional[str] = None,
    top_k: int = 5,
) -> List[RRFResult]:
    """Find tables for a company whose Ten_Bang fuzzy-matches *table_name_query*.

    Useful when the caller already knows the table type (e.g. "bảng cân đối kế
    toán") and wants to retrieve the correct CSV without a full hybrid search.

    Args:
        company:          Ticker code OR company name (resolved automatically).
        table_name_query: Vietnamese table name to match, e.g.
                          "bảng cân đối kế toán hợp nhất".
        year:             Optional year filter (e.g. "2022").
        report_type:      Optional report type filter ("separate"/"consolidated").
        top_k:            Maximum number of results to return.

    Returns:
        List of result dicts sorted by fuzzy Ten_Bang match score (0-100),
        highest first.  Each dict contains all metadata fields plus
        ``table_name_score`` (the fuzzy match score).
    """
    from thefuzz import fuzz  # soft dependency already used by pipeline/

    _ensure_resources()
    ticker = _resolve_ticker(company)
    query_lower = table_name_query.lower()

    candidates = []
    for doc in (_doc_mapping or []):
        if doc.get("Ma_Doanh_Nghiep", "").strip() != ticker:
            continue
        if year and str(doc.get("Nam_Tai_Chinh", "")).strip() != str(year):
            continue
        if report_type:
            val = doc.get("Loai_Bao_Cao", "").strip()
            if val not in (report_type, "unknown"):
                continue
        ten_bang = str(doc.get("Ten_Bang", "")).lower()
        score = fuzz.token_set_ratio(query_lower, ten_bang)
        candidates.append({**doc, "table_name_score": score})

    candidates.sort(key=lambda x: x["table_name_score"], reverse=True)
    return candidates[:top_k]


def search_by_column_name(
    company: str,
    column_query: str,
    year: Optional[str] = None,
    report_type: Optional[str] = None,
    top_k: int = 5,
) -> List[RRFResult]:
    """Find tables for a company that contain a column matching *column_query*.

    Uses the ``col_names`` payload field written by the indexing phase.
    Requires a re-index after the corresponding ``data_pipeline.py`` update
    that adds ``col_names`` to the Qdrant payload and BM25 doc_mapping.

    Args:
        company:      Ticker code OR company name (resolved automatically).
        column_query: Column name to search for, e.g. "Số cuối năm",
                      "31/12/2022", "lợi nhuận".
        year:         Optional year filter.
        report_type:  Optional report type filter.
        top_k:        Maximum number of results to return.

    Returns:
        List of result dicts sorted by fuzzy col_names match score (0-100),
        highest first.  Each dict contains all metadata fields plus
        ``col_name_score`` (the fuzzy match score).

    Note:
        If ``col_names`` is empty in the payload (index built before this
        feature was added), falls back to scanning ``line_items`` instead.
    """
    from thefuzz import fuzz

    _ensure_resources()
    ticker = _resolve_ticker(company)
    query_lower = column_query.lower()

    candidates = []
    for doc in (_doc_mapping or []):
        if doc.get("Ma_Doanh_Nghiep", "").strip() != ticker:
            continue
        if year and str(doc.get("Nam_Tai_Chinh", "")).strip() != str(year):
            continue
        if report_type:
            val = doc.get("Loai_Bao_Cao", "").strip()
            if val not in (report_type, "unknown"):
                continue
        # Prefer col_names field; fall back to line_items if not yet indexed
        search_field = doc.get("col_names", "") or doc.get("line_items", "")
        score = fuzz.partial_ratio(query_lower, search_field.lower())
        candidates.append({**doc, "col_name_score": score})

    candidates.sort(key=lambda x: x["col_name_score"], reverse=True)
    return candidates[:top_k]


# =============================================================================
# CLI (for quick testing from terminal)
# =============================================================================

def _cli() -> None:
    import argparse
    _configure_logging()
    p = argparse.ArgumentParser(description="ViFinQA Hybrid Search CLI")
    p.add_argument("--query",   type=str, default="Lợi nhuận sau thuế")
    p.add_argument("--ticker",  type=str, default=None)
    p.add_argument("--year",    type=str, default=None)
    p.add_argument("--top-k",   type=int, default=DEFAULT_TOP_K)
    args = p.parse_args()

    results = run_hybrid_search(args.query, args.top_k, args.ticker, args.year)
    print(f"\n{'='*70}")
    print(f"  {len(results)} result(s) for: \"{args.query}\"")
    print(f"{'='*70}")
    for i, r in enumerate(results, 1):
        print(f"  #{i:<3} RRF={r['rrf_score']:.6f}  "
              f"Dense={r.get('dense_rank', '-')}  BM25={r.get('sparse_rank', '-')}")
        print(f"       {r.get('Ten_Bang','?')}  ({r.get('Ma_Doanh_Nghiep','?')} "
              f"{r.get('Nam_Tai_Chinh','?')}  {r.get('Loai_Bao_Cao','?')})")
        print(f"       {r.get('csv_path','')[-70:]}")


if __name__ == "__main__":
    _cli()

