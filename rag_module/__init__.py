"""
rag_module/__init__.py
======================
Package entry point for the ViFinQA RAG module.

Exposes the top-level search API so a Kaggle notebook can do:

    from rag_module.search_engine import run_hybrid_search
    results = run_hybrid_search("Lợi nhuận sau thuế của FPT năm 2023")
"""
from rag_module.search_engine import run_hybrid_search, search_by_table_name, search_by_column_name
from rag_module.search_engine import run_hybrid_search, search_by_company_and_content

__all__ = ["run_hybrid_search", "search_by_company_and_content"]

__all__ = ["run_hybrid_search", "search_by_table_name", "search_by_column_name"]

