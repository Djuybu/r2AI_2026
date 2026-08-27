## 2026-08-27T16:57:34Z
You are Worker 4 implementing Milestone 4: Kaggle Notebook Reflection & JSON Synchronization.

Your working directory: d:/hobby_project/cocopila/r2AI_2026/.agents/worker_m4/
You must read:
- ORIGINAL_REQUEST.md: d:/hobby_project/cocopila/r2AI_2026/.agents/ORIGINAL_REQUEST.md
- PROJECT.md: d:/hobby_project/cocopila/r2AI_2026/PROJECT.md
- Explorer Survey 3 Report: d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_3/survey_report.md
- Source files:
  - `pipeline/src/nodes/query_parser.py`
  - `pipeline/src/nodes/schema_mapper.py`
  - `pipeline/src/prompts/query_parser.yaml`
  - `pipeline/src/prompts/schema_mapper.yaml`
  - `pipeline/src/prompts/code_generator.yaml`

File Ownership (You exclusively own and edit this file):
- `notebooks/kaggle_bootstrap.ipynb`
Do NOT touch any other source files.

Key requirements:
1. Inspect `notebooks/kaggle_bootstrap.ipynb` (ensure valid Jupyter Notebook v4 JSON).
2. Synchronize Cell 11 (0-indexed, Section 2 Prompt Templates):
   - Update `PROMPT_QUERY_PARSER` with negative constraints against generic legal terms and corrected few-shot mapping for `CTCP Chứng khoán FPT` -> `FTS`.
   - Update `PROMPT_CODE_GENERATOR` to enforce `.astype(str)` before `.str.contains(..., case=False, na=False, regex=False)`.
3. Synchronize Cell 15 (0-indexed, Section 4 Node 1 Query Parser):
   - Update with the latest Node 1 code from `pipeline/src/nodes/query_parser.py`: `NEGATIVE_BLOCKLIST`, `ALIAS_TICKER_MAP`, `_normalize_company_name`, `_clean_financial_content`, `_fallback_parse_query`, `parse_query_node` (ensuring `ticker` and `ten_cong_ty` state sync).
4. Synchronize Cell 19 (0-indexed, Section 4 Node 3 Schema Mapper):
   - Update with the latest Node 3 code from `pipeline/src/nodes/schema_mapper.py`: `AUXILIARY_COL_REGEX`, `_is_numeric_value`, `_is_code_or_index_column`, `_extract_useful_columns` (with `avg_str_len` & `letter_ratio`), `_find_label_column` (longest string & text density), `_find_value_column` (% support & safe column names), `schema_mapper_node`.
5. Check if Cell 21 (Node 4) or Cell 23 (Node 5) need alignment with `sanitize_code_str` in `pipeline/src/nodes/executor.py` and sync if appropriate.
6. Validate JSON integrity of `notebooks/kaggle_bootstrap.ipynb`:
   - Run python validation script `import json; json.load(open('notebooks/kaggle_bootstrap.ipynb', encoding='utf-8'))`.
   - Ensure all cells are properly formatted as list of strings with `\n` line endings.
   - Ensure python syntax in every updated cell is 100% valid (using `ast.parse`).
