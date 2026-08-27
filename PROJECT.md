# Project: Cocopila ViFinQA Data Agent Pipeline — Phase 1 Hotfix & Rule-based

## Architecture
Cocopila ViFinQA is a deterministic, LangGraph-based financial data agent pipeline designed for Vietnamese financial statements (BCTC).
The pipeline flows through 5 core nodes:
1. **Node 1: Query Parser & Entity Extraction (`pipeline/src/nodes/query_parser.py`)**: Parses natural language Vietnamese financial questions into structured queries (`ticker`, `year`, `metric`, `thao_tac`, `tieu_chi_phu`). Uses `TickerEntityResolver` with `NEGATIVE_BLOCKLIST` and `ALIAS_TICKER_MAP`.
2. **Node 2: Data Discovery / Search Engine (`pipeline/src/nodes/data_discovery.py`)**: Locates relevant consolidated or separate financial tables (local CSV or Qdrant in production; test runner uses direct local CSV lookup).
3. **Node 3: Schema Mapper Resolution (`pipeline/src/nodes/schema_mapper.py`)**: Inspects target CSV tables, eliminates auxiliary index/STT columns via text density heuristics, identifies `label_column` (longest average text string) and `value_column` (numeric / percentage `%` match).
4. **Node 4: Code Generator (`pipeline/src/nodes/code_generator.py`)**: Synthesizes Pandas retrieval code using safe `.astype(str).str.contains(..., regex=False)`.
5. **Node 5: Code Executor Sandbox (`pipeline/src/nodes/executor.py`)**: Executes code in an AST-validated sandbox with automatic syntax sanitization and value extraction.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---|---|---|---|
| F1 | TickerEntityResolver Precedence | Order: Parentheses `(TICKER)` -> Brand Alias -> Longest Clean Company Name -> Standalone Uppercase Word -> Fallback | M1 | Survey 1 |
| F2 | NEGATIVE_BLOCKLIST Expansion | Block 48 generic corporate terms and financial abbreviations (CTCP, TMCP, TCTD, TNDN, GTGT, VND, etc.) | M1 | Survey 1 |
| F3 | Vietnamese Brand Alias Map | Map 85+ colloquial / brand company names (e.g. Địa ốc No Va -> NVL, Đèo Cả -> HHV, Chứng khoán FPT -> FTS) | M1 | Survey 1 |
| F4 | Query Content Cleaner | `_clean_financial_content` strips action verbs, measurement units, and trailing question noise | M1 | Survey 1 |
| F5 | Ticker State Sync | Ensure `parsed_query["ticker"]` and `parsed_query["ten_cong_ty"]` are strictly synchronized to resolved ticker | M1 | Survey 1 |
| F6 | Query Parser Prompt Fix | Add negative constraints and fix few-shot mapping for `CTCP Chứng khoán FPT` -> `FTS` | M1 | Survey 1 |
| F7 | STT / Index Column Elimination | `AUXILIARY_COL_REGEX` & text density checks (`avg_str_len <= 4.0`, `letter_ratio < 0.35`) & float index `1.0, 2.0` | M2 | Survey 2 |
| F8 | Longest String Label Selection | `_find_label_column` selects candidate with maximum `avg_str_len` and high `letter_ratio` | M2 | Survey 2 |
| F9 | Value Column Percentage Support | `_is_numeric_value` strips `%`, `$`; `_find_value_column` prioritizes `%` / voting rights columns | M2 | Survey 2 |
| F10 | Safe `.astype(str)` Protection | Enforce `.astype(str)` before `.str.contains` across prompts, schema mapper, and executor sanitizer | M2 | Survey 2 |
| F11 | Local CSV Test Suite (Zero Qdrant) | `test_phase1_fixes.py` covering unit tests, 5 critical failure cases (Q28, Q42, Q32, Q41, Q19), and 23 baseline regression cases (45/45 PASS) | M3 | Survey 3 |
| F12 | Kaggle Notebook Synchronization | Sync Node 1, Node 3, and Prompts to Cells 11, 15, 19, 23 in `notebooks/kaggle_bootstrap.ipynb` with JSON and AST validation | M4 | Survey 3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| M1 | Node 1 Query Parser & Entity Resolver Hotfix | `pipeline/src/nodes/query_parser.py`, `pipeline/src/prompts/query_parser.yaml` | none | DONE |
| M2 | Node 3 Schema Mapper Resolution Hotfix | `pipeline/src/nodes/schema_mapper.py`, `pipeline/src/nodes/executor.py`, `pipeline/src/prompts/code_generator.yaml` | none | DONE |
| M3 | E2E Local CSV Test Suite & Verification | `pipeline/tests/test_phase1_fixes.py` (Unit, 5 Hotfix cases, 23 Baseline cases) | M1, M2 | DONE |
| M4 | Notebook Synchronization & JSON Validation | `notebooks/kaggle_bootstrap.ipynb` (Cells 11, 15, 19, 23) | M1, M2, M3 | DONE |

## Interface Contracts
### Node 1 ↔ Node 2 / Node 3
- `state["parsed_query"]["ticker"]`: str (always uppercase 3-5 chars, e.g. "NVL", "HHV", "FTS", "DLG", never corporate words like "CTCP")
- `state["parsed_query"]["ten_cong_ty"]`: str (synchronized with `ticker`)
- `state["parsed_query"]["metric"]`: str (cleaned financial content without action verbs or trailing noise)
- `state["parsed_query"]["year"]`: str (e.g. "2021", "2016")

### Node 3 ↔ Node 4 / Node 5
- `state["column_mapping"]["label_column"]`: str (raw column name of financial line item text column)
- `state["column_mapping"]["value_column"]`: str (raw column name of financial number / percentage column)
- `state["schema"]["useful_columns"]`: list of dicts with keys `raw_column`, `column_name`, `data_type`, `avg_str_len`, `letter_ratio`, `is_aux_code`

## Code Layout
- `pipeline/src/nodes/query_parser.py`: Node 1 implementation (M1)
- `pipeline/src/prompts/query_parser.yaml`: Node 1 prompt (M1)
- `pipeline/src/nodes/schema_mapper.py`: Node 3 implementation (M2)
- `pipeline/src/nodes/executor.py`: Node 5 AST executor sanitizer (M2, M5)
- `pipeline/src/prompts/code_generator.yaml`: Prompt rules for .astype(str) (M2)
- `pipeline/tests/test_phase1_fixes.py`: Comprehensive test suite (M3 - 45/45 pass)
- `notebooks/kaggle_bootstrap.ipynb`: Mirror notebook (M4 - Cells 11, 15, 19, 23 valid JSON/AST)
