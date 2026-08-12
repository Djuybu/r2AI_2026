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

import logging
import pickle
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
from sentence_transformers import SentenceTransformer

# =============================================================================
# CONFIGURATION
# =============================================================================

_HERE = Path(__file__).parent   # always points to the rag_module/ directory

# --- LOCAL paths (default — works when running from the project root) ---
QDRANT_DB_PATH       = _HERE / "qdrant_local_db"
BM25_PATH            = _HERE / "bm25_index.pkl"
CODE_STOCK_CSV       = _HERE / "code_stock.csv"

# --- KAGGLE paths (uncomment and set your Kaggle dataset name) ---
# _KAGGLE_ROOT       = Path("/kaggle/input/your-dataset-name/rag_module")
# QDRANT_DB_PATH     = _KAGGLE_ROOT / "qdrant_local_db"
# BM25_PATH          = _KAGGLE_ROOT / "bm25_index.pkl"
# CODE_STOCK_CSV     = _KAGGLE_ROOT / "code_stock.csv"

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
        raise FileNotFoundError(
            f"BM25 index not found: {pkl_path}\n"
            "Run data_pipeline.py first to build the index."
        )
    with open(pkl_path, "rb") as f:
        data = pickle.load(f)
    bm25        = data["bm25"]
    doc_mapping = data["doc_mapping"]
    logger.info("BM25 index loaded. Corpus size: %d documents.", bm25.corpus_size)
    return bm25, doc_mapping


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
    for company_name, code in company_map:
        if company_name.lower() in q_lower:
            ticker = code
            break

    # Fallback: parenthesised ticker e.g. "(VCB)"
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

    must = [
        FieldCondition(key="Ma_Doanh_Nghiep", match=MatchValue(value=ticker)),
        FieldCondition(key="Nam_Tai_Chinh",   match=MatchValue(value=year)),
    ]
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
        if meta.get("Ma_Doanh_Nghiep", "").strip() != ticker.strip():
            continue
        if str(meta.get("Nam_Tai_Chinh", "")).strip() != str(year).strip():
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

    if not ticker or not year:
        logger.warning("Could not extract ticker/year from query: %s", query)
        return []

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

