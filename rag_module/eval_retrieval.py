"""
eval_retrieval.py
=================
Batch evaluation script for the ViFinQA RAG pipeline.

Reads questions from questions/questions.jsonl, auto-parses each question,
runs hybrid search, and displays ranked results for visual verification.

Usage:
    # From project root:
    python rag_module/eval_retrieval.py --question-id 4 --show-data
    python rag_module/eval_retrieval.py --num-questions 10
    python rag_module/eval_retrieval.py --question-id 1 --num-questions 5 --show-data
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# =============================================================================
# CONFIGURATION
# =============================================================================

_HERE = Path(__file__).parent    # rag_module/

QUESTIONS_PATH  = _HERE.parent / "questions" / "questions.jsonl"
CODE_STOCK_CSV  = _HERE / "code_stock.csv"

# --- KAGGLE override (uncomment and set your dataset name) ---
# _KAGGLE_ROOT   = Path("/kaggle/input/your-dataset-name/rag_module")
# CODE_STOCK_CSV = _KAGGLE_ROOT / "code_stock.csv"
# QUESTIONS_PATH = Path("/kaggle/input/your-dataset-name/questions/questions.jsonl")

# =============================================================================
# Imports from search_engine (same package)
# =============================================================================

try:
    from rag_module.search_engine import (
        load_company_map,
        parse_query,
        run_hybrid_search,
    )
except ImportError:
    # Fallback: running as a script directly from project root
    sys.path.insert(0, str(_HERE.parent))
    from rag_module.search_engine import (
        load_company_map,
        parse_query,
        run_hybrid_search,
    )


# =============================================================================
# Helpers
# =============================================================================

def load_questions(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Questions file not found: {path}")
    questions = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                questions.append(json.loads(line))
    return questions


def _show_result(
    rank: int,
    result: Dict[str, Any],
    show_data: bool = False,
    max_rows: int = 5,
) -> None:
    csv_path = result.get("csv_path", "")
    tname    = result.get("Ten_Bang", Path(csv_path).stem if csv_path else "unknown")
    rrf      = result.get("rrf_score", 0.0)

    print(f"\n  #{rank:<3} RRF={rrf:.6f}  "
          f"Dense={result.get('dense_rank', '-')}  BM25={result.get('sparse_rank', '-')}")
    print(f"       Table : {tname}")
    print(f"       Type  : {result.get('Loai_Bao_Cao', 'unknown')}")
    print(f"       Unit  : {result.get('Don_Vi_Tinh', 'unknown')}")
    tail = csv_path[-70:] if len(csv_path) > 70 else csv_path
    print(f"       Path  : ...{tail}" if len(csv_path) > 70 else f"       Path  : {tail}")

    if show_data and csv_path:
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
            meta_cols = ["Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "Nam_Tai_Chinh",
                         "Loai_Bao_Cao", "Ten_Bang", "Don_Vi_Tinh", "Tep_Nguon"]
            data_cols = [c for c in df.columns if c not in meta_cols][:5]
            if data_cols:
                pd.set_option("display.max_colwidth", 45)
                pd.set_option("display.width", 130)
                print(f"\n       Data preview ({len(df)} rows):")
                print("       " + df[data_cols].head(max_rows)
                      .to_string(index=False).replace("\n", "\n       "))
        except Exception as exc:
            print(f"       WARNING: Cannot read CSV: {exc}")


def evaluate_question(
    q:           Dict[str, Any],
    company_map: List,
    top_k:       int  = 5,
    show_data:   bool = False,
) -> bool:
    qid      = q["id"]
    question = q["question"]

    ticker, year, report_type = parse_query(question, company_map)

    print(f"\n{'='*72}")
    print(f"  Q{qid}: {question}")
    print(f"{'-'*72}")
    print(f"  Parsed -> Ticker: {ticker or '(not found)'}  |  "
          f"Year: {year or '(not found)'}  |  Type: {report_type}")

    if not ticker or not year:
        print("  WARNING: Could not extract ticker or year -- skipping.")
        return False

    results = run_hybrid_search(question, top_k=top_k,
                                ticker=ticker, year=year, report_type=report_type)

    if not results:
        print(f"  No results for ticker='{ticker}', year='{year}', type='{report_type}'.")
        return False

    print(f"\n  Found {len(results)} result(s). Top {min(top_k, len(results))}:\n")
    print("  " + "-" * 70)
    for i, r in enumerate(results[:top_k], start=1):
        _show_result(i, r, show_data=show_data)
    print("  " + "-" * 70)
    return True


# =============================================================================
# CLI
# =============================================================================

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="eval_retrieval",
        description="Evaluate hybrid retrieval against the ViFinQA question database.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--questions",      type=Path, default=QUESTIONS_PATH)
    p.add_argument("--code-stock-csv", type=Path, default=CODE_STOCK_CSV)
    p.add_argument("--question-id",    type=int,  default=None)
    p.add_argument("--num-questions",  type=int,  default=1)
    p.add_argument("--top-k",          type=int,  default=5)
    p.add_argument("--show-data",      action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv)

    print("\n" + "="*72)
    print("  ViFinQA -- Retrieval Evaluation")
    print("="*72 + "\n")

    # Company map is cheap to load; the heavy resources (Qdrant, model, BM25)
    # are lazy-loaded on the first call to run_hybrid_search.
    company_map = load_company_map(args.code_stock_csv)
    print(f"Company map loaded: {len(company_map)} entries.\n")

    try:
        all_questions = load_questions(args.questions)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    if args.question_id is not None:
        start = next((i for i, q in enumerate(all_questions)
                      if q["id"] == args.question_id), None)
        if start is None:
            print(f"ERROR: Question ID {args.question_id} not found.")
            sys.exit(1)
        selected = all_questions[start: start + args.num_questions]
    else:
        selected = all_questions[: args.num_questions]

    print(f"Testing {len(selected)} question(s) from {args.questions}\n")

    passed = 0
    for q in selected:
        ok = evaluate_question(q, company_map,
                               top_k=args.top_k, show_data=args.show_data)
        if ok:
            passed += 1

    print(f"\n{'='*72}")
    print(f"  Evaluation complete: {passed} / {len(selected)} questions returned results.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
