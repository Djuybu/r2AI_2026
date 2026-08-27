# Progress Log

- **Status**: Completed
- **Last visited**: 2026-08-28T00:01:00+07:00
- **Current Step**: Task completed. Handoff report prepared.
- **Summary of actions**:
  1. Inspected `notebooks/kaggle_bootstrap.ipynb` (31 cells, nbformat 4.4).
  2. Synchronized Cell 11 (Prompt Templates): `PROMPT_QUERY_PARSER` with `CRITICAL NEGATIVE RULES` against generic legal forms (CTCP, TMCP, etc.), few-shot mappings for FTS, EIB, HHV, NVL; `PROMPT_CODE_GENERATOR` with `.astype(str)` before `.str.contains(..., case=False, na=False, regex=False)`.
  3. Synchronized Cell 15 (Node 1 Query Parser): `NEGATIVE_BLOCKLIST`, `ALIAS_TICKER_MAP` (Novaland -> NVL, Đèo Cả -> HHV, Đức Long Gia Lai -> DLG, etc.), `_normalize_company_name`, `_clean_financial_content`, `_fallback_parse_query`, `parse_query_node` (strict ticker/company sync).
  4. Synchronized Cell 19 (Node 3 Schema Mapper): `AUXILIARY_COL_REGEX`, `_AUXILIARY_CODE_COLUMNS`, `_is_code_or_index_column` (text density & float index detection), `_extract_useful_columns` (`avg_str_len` & `letter_ratio`), `_find_label_column` (longest string & text density), `_find_value_column` (% support), `schema_mapper_node`.
  5. Synchronized Cell 23 (Node 5 AST Sandbox & Executor): `sanitize_code_str` with `.astype(str)` auto-insertion (Fix bug 3).
  6. Formatted all cell `source` fields as list of strings with `\n` line endings and saved with `indent=1`.
  7. Ran verification script validating 100% JSON structure and AST parsing across all code cells.
