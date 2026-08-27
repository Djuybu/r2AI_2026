## 2026-08-27T16:51:41Z
You are Worker 2 implementing Milestone 2: Node 3 Schema Mapper Resolution Hotfix.

Your working directory: d:/hobby_project/cocopila/r2AI_2026/.agents/worker_m2/
You must read:
- ORIGINAL_REQUEST.md: d:/hobby_project/cocopila/r2AI_2026/.agents/ORIGINAL_REQUEST.md
- PROJECT.md: d:/hobby_project/cocopila/r2AI_2026/PROJECT.md
- Explorer Survey 2 Report: d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_2/survey_report.md

File Ownership (You exclusively own and edit these files):
1. `pipeline/src/nodes/schema_mapper.py`
2. `pipeline/src/nodes/executor.py`
3. `pipeline/src/prompts/code_generator.yaml`
Do NOT touch any other files.

Tasks to implement:
1. In `pipeline/src/nodes/schema_mapper.py`:
   - Define `AUXILIARY_COL_REGEX` to catch `stt`, `số tt`, `số thứ tự`, `sothutu`, `mã số`, `mãsố`, `thuyết minh`, `thuyếtminh`, `ghi chú`, `note`, `code`, `ms`, `tm`, `cột_\d+`, `unnamed.*`.
   - Update `_is_numeric_value(val)` to strip `%`, `$`, `VND`, parentheses `(123)`, minus/plus signs, commas, periods.
   - Update `_is_code_or_index_column(series, col_name)` with:
     - Header regex check (`AUXILIARY_COL_REGEX`).
     - Text density check: if `avg_len <= 4.0` and `letter_ratio < 0.35` -> return `True`.
     - Multi-pattern token check: float index `\d+\.0+`, roman numerals, index numbering `\d+\.\d+`.
   - Update `_extract_useful_columns(df)`: Compute `avg_str_len` and `letter_ratio` per column, filter out empty rows, classify `is_aux_code` and `data_type`.
   - Update `_find_label_column(useful_columns, columns)`:
     - Select from non-auxiliary text columns the column with `max(avg_str_len)` where `letter_ratio >= 0.40`.
     - Fallback gracefully to max `avg_str_len` text column or first non-metadata column.
   - Update `_find_value_column(useful_columns, label_col, tieu_chi_phu, columns)`:
     - Protect against non-string column names (`str(c_name)`, `str(r_name)`).
     - Support percentage (`%`), `tỷ lệ`, `biểu quyết`, `sở hữu`, `lãi suất` keyword matching.
     - Match tieu_chi_phu via exact/substring, % matching, and fuzzy matching.
     - Prioritize non-auxiliary numeric columns.
2. In `pipeline/src/nodes/executor.py`:
   - In `sanitize_code_str(code_str)`: Ensure automatic insertion of `.astype(str)` before any `.str.contains` / `.str.` operations if missing:
     `re.sub(r"(df\[\s*['\"][^'\"]+['\"]\s*\])(?!\.astype\(str\))\.str\.", r"\1.astype(str).str.", code_str)`
3. In `pipeline/src/prompts/code_generator.yaml`:
   - Explicitly instruct the LLM to always use `df['{label_col}'].astype(str).str.contains(..., case=False, na=False, regex=False)`.
4. Run python verification: Execute python tests on Node 3 and Node 5 across real CSV files in `rag_module/ViFinQA/processed_data/` (specifically testing Q28, Q42, Q32, Q41, Q19 and baseline cases). Verify 0 regression.
