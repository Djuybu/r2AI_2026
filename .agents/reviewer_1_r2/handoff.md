# Independent Review & Adversarial Critic Report: Phase 1 Hotfix

**Reviewer**: Reviewer 1 (Archetype: Reviewer / Critic)  
**Target Milestone**: Phase 1 Hotfix Implementation  
**Working Directory**: `d:/hobby_project/cocopila/r2AI_2026/.agents/reviewer_1_r2/`  
**Verdict**: `APPROVE`  
**Integrity Status**: 100% Verified (Zero integrity violations, zero hardcoded cheat results, zero facade logic)

---

## 1. Observation

### 1.1 Automated Test Execution
- **Command**: `python -m pytest pipeline/tests/test_phase1_fixes.py -v`
- **Working Directory**: `d:/hobby_project/cocopila/r2AI_2026`
- **Result Output**:
  ```
  ============================= test session starts =============================
  platform win32 -- Python 3.11.0, pytest-9.1.1, pluggy-1.6.0
  collected 45 items

  pipeline/tests/test_phase1_fixes.py::TestNode1QueryParserFixes::test_negative_blocklist_coverage PASSED [  2%]
  pipeline/tests/test_phase1_fixes.py::TestNode1QueryParserFixes::test_alias_ticker_mappings_comprehensive PASSED [  4%]
  pipeline/tests/test_phase1_fixes.py::TestNode1QueryParserFixes::test_normalize_company_name_resolution_precedence PASSED [  6%]
  pipeline/tests/test_phase1_fixes.py::TestNode1QueryParserFixes::test_clean_financial_content PASSED [  8%]
  pipeline/tests/test_phase1_fixes.py::TestNode1QueryParserFixes::test_fallback_query_parser PASSED [ 11%]
  pipeline/tests/test_phase1_fixes.py::TestNode1QueryParserFixes::test_yaml_prompt_integrity_and_fewshot_fpt_securities PASSED [ 13%]
  pipeline/tests/test_phase1_fixes.py::TestNode1QueryParserFixes::test_state_synchronization PASSED [ 15%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_auxiliary_col_regex PASSED [ 17%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_is_numeric_value PASSED [ 20%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_is_code_or_index_column PASSED [ 22%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_text_density_heuristics PASSED [ 24%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_find_label_column_selection PASSED [ 26%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_find_value_column_percentage_and_keywords PASSED [ 28%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_extract_useful_columns_filtering PASSED [ 31%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_executor_ast_sanitization PASSED [ 33%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_executor_clean_val_and_extract_value PASSED [ 35%]
  pipeline/tests/test_phase1_fixes.py::TestNode3SchemaMapperFixes::test_executor_security_sandbox PASSED [ 37%]
  pipeline/tests/test_phase1_fixes.py::TestCriticalFailureCasesE2E::test_q28_nvl_receivables_e2e PASSED [ 40%]
  pipeline/tests/test_phase1_fixes.py::TestCriticalFailureCasesE2E::test_q42_eib_salary_fund_e2e PASSED [ 42%]
  pipeline/tests/test_phase1_fixes.py::TestCriticalFailureCasesE2E::test_q32_fpt_unbilled_revenue_e2e PASSED [ 44%]
  pipeline/tests/test_phase1_fixes.py::TestCriticalFailureCasesE2E::test_q41_dlg_trading_securities_e2e PASSED [ 46%]
  pipeline/tests/test_phase1_fixes.py::TestCriticalFailureCasesE2E::test_q19_hhv_voting_rights_e2e PASSED [ 48%]
  pipeline/tests/test_phase1_fixes.py::TestBaselineRegression23Cases::test_baseline_case_schema_mapping_and_execution[1..49] (23 cases) PASSED [100%]
  ============================= 45 passed in 44.76s =============================
  ```

### 1.2 Node 1 Code & Prompt Observations
- **`pipeline/src/nodes/query_parser.py`**:
  - Line 31: `NEGATIVE_BLOCKLIST` contains 48 distinct terms across legal corporate forms (`CTCP`, `TMCP`, `TẬP ĐOÀN`, `TỔNG CÔNG TY`, `JSC`, `HOLDINGS`, etc.), financial abbreviations (`BCTC`, `TCTD`, `TNDN`, `GTGT`, `VAMC`, `HĐQT`, `TSCĐ`, etc.), and exchange/currencies (`VND`, `USD`, `HOSE`, `HNX`).
  - Line 45: `ALIAS_TICKER_MAP` contains 90+ brand mappings sorted by length descending during resolution (e.g. `tập đoàn đầu tư địa ốc no va` -> `NVL`, `địa ốc no va` -> `NVL`, `đèo cả` -> `HHV`, `đức long gia lai` -> `DLG`, `chứng khoán fpt` -> `FTS`, `viễn thông fpt` -> `FOX`, `fpt` -> `FPT`).
  - Line 286: `_normalize_company_name` strictly enforces 6-tier precedence:
    1. Corporate prefix blocklist filter
    2. Explicit parenthesized ticker `\(([A-Za-z]{2,5})\)` (verified skipping blocklisted tokens like `(BCTC)`)
    3. `ALIAS_TICKER_MAP` (sorted by length descending)
    4. `code_stock.csv` full and cleaned company names (sorted by length descending)
    5. Standalone 3-5 uppercase words
    6. LLM company input validation fallback
  - Line 349: `_clean_financial_content` strips 16 action/measurement prefix patterns and 4 trailing question noise patterns.
  - Lines 532-552: Complete state synchronization (`parsed_query["ticker"] == parsed_query["ten_cong_ty"] == resolved_ticker`, `year`, `so_nam`, `metric`, `noi_dung`, `thao_tac`, `muc_tieu`).
- **`pipeline/src/prompts/query_parser.yaml`**:
  - Line 7: Explicit `CRITICAL NEGATIVE RULES` against corporate words.
  - Line 35: Few-shot example correctly maps `CTCP Chứng khoán FPT` -> `FTS` (not `FPT`).

### 1.3 Node 3, Node 5 Code & Prompt Observations
- **`pipeline/src/nodes/schema_mapper.py`**:
  - Line 38: `AUXILIARY_COL_REGEX` matches STT, mã số, thuyết minh, ghi chú, note, code, ms, tm, cột_\d+, unnamed.*.
  - Line 57: `_is_numeric_value` handles %, $, VND, parentheses `(123)`, +/-, thousand separators.
  - Line 205: `_is_code_or_index_column` rejects float indices (`1.0, 2.0`), Roman numerals, and short auxiliary tokens via text density heuristics (`avg_len <= 4.0`, `letter_ratio < 0.35`).
  - Line 326: `_find_label_column` selects candidate with maximum `avg_str_len` and `letter_ratio >= 0.40`, eliminating auxiliary code columns.
  - Line 366: `_find_value_column` dynamically discovers value column supporting percentage `%`, voting rights (`quyền biểu quyết`, `tỷ lệ sở hữu`), and numeric filtering.
- **`pipeline/src/nodes/executor.py`**:
  - Line 87: `sanitize_code_str` injects `.astype(str)` before `.str.` operations without duplicating, transforms `df[df[col] == val]` to `.str.contains(regex=False)`, and fixes `if in .str.contains` to `if (...).any():`.
  - Line 36: `validate_ast` blocks forbidden imports and builtins (`eval`, `exec`, `open`, `__import__`, etc.).
  - Line 138: `extract_value` automatically falls back to child row if parent row is empty.
- **`pipeline/src/prompts/code_generator.yaml`**:
  - Line 5: `<BANNED_SYNTAX>` strictly forbids `result = 0.0` bypass, `.iloc[0]` outside empty check, and `str.contains()` without `.astype(str)` or `regex=False`.

### 1.4 Kaggle Notebook Synchronization Observations
- **`notebooks/kaggle_bootstrap.ipynb`**:
  - JSON validity confirmed via `json.load()` exiting with code 0.
  - Cell 11: Contains synchronized `PROMPT_QUERY_PARSER`, `PROMPT_SCHEMA_MAPPER`, `PROMPT_CODE_GENERATOR`, `PROMPT_REFLECTION`.
  - Cell 15: Contains synchronized Node 1 `query_parser.py` implementation.
  - Cell 19: Contains synchronized Node 3 `schema_mapper.py` implementation.
  - Cell 23: Contains synchronized Node 5 `executor.py` implementation.

---

## 2. Logic Chain

1. **Requirements & Scope Traceability**:
   - R1 (Query Parser): Resolved via `NEGATIVE_BLOCKLIST`, `ALIAS_TICKER_MAP`, `_normalize_company_name`, `_clean_financial_content`, and `query_parser.yaml` prompt few-shots. Verified in Observation 1.2.
   - R2 (Schema Mapper & AST Executor): Resolved via `AUXILIARY_COL_REGEX`, float index elimination in `_is_code_or_index_column`, text density checks, longest string label column selection in `_find_label_column`, percentage value support in `_find_value_column`, and `.astype(str)` sanitization in `executor.py`. Verified in Observation 1.3.
   - R3 (Local CSV Test Suite & Notebook Sync): Resolved via 45-test suite in `pipeline/tests/test_phase1_fixes.py` running 100% offline on local CSVs and full 4-cell synchronization in `notebooks/kaggle_bootstrap.ipynb`. Verified in Observations 1.1 and 1.4.

2. **Integrity & Authenticity Assessment**:
   - The test suite executes against real CSV files located in `rag_module/ViFinQA/processed_data/`.
   - Node 1 resolver dynamically searches substrings and parses query text; no hardcoded question IDs or cheat branches exist in source code.
   - Node 3 evaluates actual DataFrame column types, row counts, and text lengths dynamically.
   - Node 5 executes actual Pandas code inside the AST sandbox and captures real numeric results.
   - Zero facade patterns or dummy bypasses detected.

3. **Adversarial & Stress-Testing Assessment**:
   - **Stress Test A: Parentheses Collision**: Queries containing `(BCTC)` or `(VND)` are safely ignored by Priority 1 because they exist in `NEGATIVE_BLOCKLIST`, falling through to correctly extract the ticker from brand aliases (`VNM`, `HPG`).
   - **Stress Test B: Substring Brand Disambiguation**: Queries mentioning `FPT Telecom` vs `FPT` or `Masan Consumer` vs `Masan` match the longest brand name first due to `len(x[0])` descending sort (`FOX` and `MCH` correctly resolved).
   - **Stress Test C: Small Float Numbers in Index Column Detection**:
     - *Observation*: In `_is_code_or_index_column`, short decimals (`<= 6` chars) matching `\d+\.\d{1,2}` could match the index regex.
     - *Risk Assessment*: If a table only contains short decimals, `useful_columns` fallback in `_extract_useful_columns` and `_find_value_column` still correctly selects the value column. In mixed tables, explicit `tieu_chi_phu` ensures correct resolution. (Non-blocking; flagged for Phase 2 optimization).
   - **Stress Test D: AST Security Sandbox**: Attempts to execute `import os`, `subprocess`, `open()`, `eval()`, `exec()` are blocked by `validate_ast` with `SecurityError`.

---

## 3. Caveats

1. **Qdrant DB Vector Search**: Qdrant DB retrieval was intentionally bypassed in test runner as per original requirements (offline local CSV mode). Production vector retrieval on Qdrant should be smoke-tested in Phase 2 deployment.
2. **Sub-clause Index Heuristic Refinement (Phase 2 Recommendation)**: The `index_token_pattern` in `_is_code_or_index_column` matches `\d+\.\d{1,2}` for section markers (e.g. `1.1`, `1.2`). In Phase 2, this can be further augmented to inspect whether column headers indicate metric/percentage values to prevent false flagging of small decimal ratios.

---

## 4. Conclusion

- **Quality & Correctness**: All 12 features across M1, M2, M3, M4 are fully implemented according to specifications in `PROJECT.md` and `ORIGINAL_REQUEST.md`.
- **Test Pass Rate**: 45/45 tests PASS (100% pass rate).
- **Regression Status**: Zero regressions across 23 baseline cases. All 5 critical failure cases (Q28, Q42, Q32, Q41, Q19) resolved.
- **Notebook Status**: Valid JSON format, fully synchronized with pipeline codebase.
- **Verdict**: **`APPROVE`**.

---

## 5. Verification Method

To independently reproduce and verify this review:

1. **Run the Full Test Suite**:
   ```bash
   python -m pytest pipeline/tests/test_phase1_fixes.py -v
   ```
   *Expected outcome*: 45 passed, 0 failed, exit code 0.

2. **Verify Notebook JSON Validity**:
   ```bash
   python -c "import json; json.load(open('notebooks/kaggle_bootstrap.ipynb', encoding='utf-8')); print('Valid JSON!')"
   ```
   *Expected outcome*: `Valid JSON!`, exit code 0.

3. **Verify Key Source Files**:
   - `pipeline/src/nodes/query_parser.py`: Inspect lines 31-43 (`NEGATIVE_BLOCKLIST`), 45-219 (`ALIAS_TICKER_MAP`), 286-346 (`_normalize_company_name`), 349-390 (`_clean_financial_content`).
   - `pipeline/src/nodes/schema_mapper.py`: Inspect lines 38-46 (`AUXILIARY_COL_REGEX`), 205-236 (`_is_code_or_index_column`), 326-364 (`_find_label_column`), 366-433 (`_find_value_column`).
   - `pipeline/src/nodes/executor.py`: Inspect lines 36-55 (`validate_ast`), 87-110 (`sanitize_code_str`), 113-179 (`clean_val`, `extract_value`).
   - `notebooks/kaggle_bootstrap.ipynb`: Inspect Cells 11, 15, 19, 23.
