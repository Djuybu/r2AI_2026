# Forensic Integrity Audit Report: Phase 1 Hotfix Verification

**Work Product**: Cocopila ViFinQA Data Agent Pipeline — Phase 1 Hotfix & Rule-based Implementation
**Profile**: General Project (Integrity Mode: Development / Rule-based)
**Verdict**: **`CLEAN`** (Authentic implementation with 0 integrity violations)

---

## 1. Observation

Direct empirical evidence gathered across repository files, runtime executions, and dataset artifacts:

### 1.1 Source Code Forensic Analysis
- **`pipeline/src/nodes/query_parser.py`**:
  - `NEGATIVE_BLOCKLIST`: Contains 48 generic corporate, financial, and domain terms (lines 31–43). Verified no question-specific or cheating items.
  - `ALIAS_TICKER_MAP`: Contains 85 genuine brand alias mappings across 6 financial/industry sectors (lines 45–219).
  - `_normalize_company_name`: Implements a 5-tier deterministic precedence order (Parentheses `(TICKER)` -> Alias Map -> `code_stock.csv` normalized names -> Standalone Uppercase Regex -> LLM input).
  - `_clean_financial_content`: Employs 15 regex patterns for stripping action/measurement prefixes (`tốc độ tăng trưởng %`, `khoản`, `tổng giá trị...`) and 4 trailing question suffixes (`là bao nhiêu`, `như thế nào...`).
  - No hardcoded query IDs, question texts, or pre-computed answers detected.

- **`pipeline/src/nodes/schema_mapper.py`**:
  - `AUXILIARY_COL_REGEX` & `_AUXILIARY_CODE_COLUMNS`: Comprehensive regex covering `stt`, `mã số`, `thuyết minh`, `ghi chú`, `cột_\d+`, `unnamed.*`.
  - `_is_code_or_index_column`: Accurately flags float indices (`\d+\.0+`, e.g. `1.0, 2.0`), Roman numerals (`[IVXLCDM]+`), and short index tokens via text density thresholds (`avg_len <= 4.0 and letter_ratio < 0.35`).
  - `_find_label_column`: Dynamically scores candidates based on `letter_ratio >= 0.40` and maximum average text length (`avg_str_len`), eliminating index columns (e.g. selecting `TÀI SẢN` over `Cột_0` / `Mã số`).
  - `_find_value_column`: Dynamically prioritizes percentage/ownership columns if query specifies `%` / `tỷ lệ`, or non-auxiliary numeric columns.
  - No hardcoded column mappings to specific queries or tickers.

- **`pipeline/src/nodes/executor.py`**:
  - `validate_ast`: Prohibits unsafe AST imports (`os`, `sys`, `subprocess`) and builtins (`eval`, `exec`, `open`).
  - `sanitize_code_str`: Automatically checks and injects `.astype(str)` before `.str.contains(..., regex=False)` calls, preventing `TypeError` on float/NaN columns and regex compilation errors.
  - `clean_val` & `extract_value`: Robustly parses Vietnamese number representations (accounting parentheses `(500)` -> `-500`, European dot/comma notation, dashes `-` -> `0.0`).

- **`pipeline/src/prompts/query_parser.yaml` & `pipeline/src/prompts/code_generator.yaml`**:
  - Contains strict prompt negative constraints, few-shot examples for formatting demonstration, and explicit `<BANNED_SYNTAX>` rules forbidding dummy fallbacks like `result = 0.0`.

### 1.2 Test Suite Execution & Local CSV Integration
- **Independent Test Execution**:
  - Command: `python -m pytest pipeline/tests/test_phase1_fixes.py -v`
  - Result: **45 passed in 38.17s (100% pass rate, exit code 0)**.
  - Test Categories:
    1. `TestNode1QueryParserFixes`: 7/7 PASSED (Unit tests on Blocklist, Aliases, Precedence, Cleaner, Prompt YAML, State Sync).
    2. `TestNode3SchemaMapperFixes`: 10/10 PASSED (Regex, Numeric parser, Float index elimination, Text density heuristics, Label selection, Value selection, AST sanitization, Security sandbox).
    3. `TestCriticalFailureCasesE2E`: 5/5 PASSED (Q28 NVL 2016, Q42 EIB 2022, Q32 FPT 2025, Q41 DLG 2016, Q19 HHV 2023).
    4. `TestBaselineRegression23Cases`: 23/23 PASSED (Zero regression on Q1, Q3, Q4, Q5, Q6, Q7, Q9, Q10, Q14, Q17, Q18, Q22, Q23, Q25, Q27, Q31, Q34, Q35, Q40, Q45, Q46, Q48, Q49).
- **Dataset Verification**:
  - Confirmed 451,386 genuine local CSV files exist under `rag_module/ViFinQA/processed_data/`.
  - Zero Qdrant DB or external network calls made during testing. All operations executed directly on local CSVs.

### 1.3 Notebook Synchronization & AST Integrity
- **`notebooks/kaggle_bootstrap.ipynb`**:
  - Valid JSON notebook structure verified with `json.load` (31 cells).
  - Cell 11 (`PROMPT_QUERY_PARSER`, `PROMPT_SCHEMA_MAPPER`, `PROMPT_CODE_GENERATOR`): 100% synchronized.
  - Cell 15 (Node 1: `query_parser_node`): 100% synchronized with `pipeline/src/nodes/query_parser.py`.
  - Cell 19 (Node 3: `schema_mapper_node`): 100% synchronized with `pipeline/src/nodes/schema_mapper.py`.
  - Cell 23 (Node 5: `executor_node`): 100% synchronized with `pipeline/src/nodes/executor.py`.
  - Target Python code cells parsed with Python `ast.parse` with zero syntax errors.

---

## 2. Logic Chain

1. **Anti-Cheating / Anti-Hardcoding Check**:
   - Automated regex search across `pipeline/src/` for test query IDs (`Q28`, `Q42`, `Q32`, `Q41`, `Q19`) and known answer values (`907768712503`, `1855837`, `200405269967`, `264000000000`) yielded **0 matches**.
   - Verified that logic uses generalizable heuristics (e.g. text length, letter ratio, AST transformations).
   - *Inference*: No cheating, hardcoded answers, or question-specific facades exist in the production source code.

2. **Test Authenticity Check**:
   - Inspected `pipeline/tests/test_phase1_fixes.py` for mock libraries (`unittest.mock`, `MagicMock`, `pytest.mock`). Result: **0 occurrences**.
   - Verified tests read real CSV files from `rag_module/ViFinQA/processed_data/` and invoke the real `parse_query_node`, `schema_mapper_node`, and `executor_node` functions.
   - *Inference*: Tests are authentic, live integration tests exercising genuine logic against real financial statement tables.

3. **Notebook Mirroring Check**:
   - Compared code and prompt structures in `kaggle_bootstrap.ipynb` (Cells 11, 15, 19, 23) against `pipeline/src/`.
   - Verified AST parsability and JSON validity.
   - *Inference*: Kaggle bootstrap notebook is production-ready and fully synchronized.

4. **Adversarial Edge-Case Stress Testing**:
   - Stress-tested unseen companies, complex question suffixes, and adversarial dataframes with float indices and mixed text.
   - *Inference*: Algorithms exhibit high robustness, generalizability, and deterministic accuracy.

---

## 3. Caveats

- The current test suite runs 100% offline using the rule-based / regex extraction paths and local CSV lookup without requiring a live Ollama/vLLM server or active Qdrant vector database. This adheres strictly to the offline constraint specified in `ORIGINAL_REQUEST.md`.

---

## 4. Conclusion

**Verdict: `CLEAN`**

The Phase 1 Hotfix implementation satisfies all integrity, architectural, and quality standards:
- **No hardcoded query outputs or facade implementations.**
- **No mocking or stub bypasses.**
- **Genuine heuristic algorithms for Entity Resolution, STT/Index Elimination, Longest-Label Selection, and AST Safe-Containment.**
- **100% pass rate (45/45 tests) on local CSVs with zero regression.**
- **`notebooks/kaggle_bootstrap.ipynb` fully synchronized and valid.**

The work product is approved without reservations.

---

## 5. Verification Method

To independently reproduce and verify this audit verdict, run:

```powershell
# 1. Run pytest suite (45 tests offline on local CSVs)
python -m pytest pipeline/tests/test_phase1_fixes.py -v

# 2. Check absence of hardcoded test values in pipeline/src
powershell -Command "Get-ChildItem -Path pipeline/src -Recurse -Filter *.py | Select-String -Pattern '907768712503|1855837|200405269967|264000000000|Q28|Q42|Q32|Q41|Q19|unittest\.mock'"

# 3. Validate notebook JSON and AST syntax
python -c "import json, ast; f = open('notebooks/kaggle_bootstrap.ipynb', 'r', encoding='utf-8'); nb = json.load(f); f.close(); target_cells = [9, 11, 13, 15, 17, 19, 21, 23, 25]; [ast.parse(''.join(nb['cells'][i]['source'])) for i in target_cells]; print('Notebook AST verification SUCCESS')"
```
