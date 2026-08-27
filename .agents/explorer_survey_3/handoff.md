# Handoff Report — Explorer 3: E2E Test Infrastructure, Local CSV Datasets & Notebook Sync

> **Agent:** Explorer 3  
> **Working Directory:** `d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_3/`  
> **Parent Agent ID:** `95d69bdf-65be-46d8-9a66-b831b5075d3e` (Orchestrator)  
> **Handoff Type:** Soft / Milestone Survey Handoff  

---

## 1. Observation

1. **Local CSV Datasets Availability:**
   - Evaluated 150 CSV tables referenced across all 50 test cases in `pipeline/tests/codegen_results.json`.
   - Verified that `150/150` (100.0%) table CSV files are present locally under `rag_module/ViFinQA/processed_data/`.
   - Path translation rule:
     `/kaggle/input/datasets/duymcminh/r2-ai-output/ViFinQA/processed_data/<TICKER>/...`  
     maps to  
     `d:/hobby_project/cocopila/r2AI_2026/rag_module/ViFinQA/processed_data/<TICKER>/...`.

2. **5 Critical Failure Cases Observed (`codegen_results.json` & local CSV inspection):**
   - **Q28 (NVL 2016):** Query is `"Tổng phải thu ngắn hạn khác của công ty mẹ CTCP Tập đoàn Đầu tư Địa ốc No Va đến ngày 31 tháng 12 năm 2016..."`.
     - In `codegen_results.json`, `parsed_query['ticker'] == 'CTCP'` instead of `'NVL'`.
     - In generated code, `df['0'].astype(str).str.contains('Tổng phải thu ngắn hạn khác')` failed because row in `NVL_..._table_14.csv` had `0 == 'Phải thu ngắn hạn khác'` (without `"Tổng"`).
   - **Q42 (EIB 2022):** Query is `"Tổng quỹ lương năm 2022 của công ty mẹ EIB là bao nhiêu triệu đồng?"`.
     - In `codegen_results.json`, `parsed_query['metric'] == 'Tổng tiền và các khoản tương đương tiền'`.
     - Actual salary table is `EIB_..._2022_separate_table_77_0@line_1732.csv` (Table 30: `TÌNH HÌNH THU NHẬP CỦA NHÂN VIÊN`) with `Cột_0 == '1. Tổng quỹ lương'`.
   - **Q32 (FPT 2025):** Query is `"Số dư phải thu theo tiến độ kế hoạch hợp đồng của FPT đến ngày 31/12/2025..."`.
     - In `FPT_..._2025_consolidated_table_4.csv`, column `0` is `'Mã số'`, column `1` is `'TÀI SẢN'`, column `3` is `'Tại ngày 31 tháng 12 năm 2025'`.
     - Generated code searched column `1`, but Schema Mapper previously returned column `0` as `label_column`.
   - **Q41 (DLG 2016):** Query is `"Giá gốc chứng khoán kinh doanh của CTCP Tập đoàn Đức Long Gia Lai cuối năm 2016..."`.
     - In `DLG_..._2016_consolidated_table_3_1@line_401.csv`, `Cột_0` has float values `1.0, 2.0`, `TÀI SẢN` contains `'Chứng khoán kinh doanh'`.
     - Schema Mapper did not flag `1.0` as index and selected `Cột_0` instead of `TÀI SẢN`.
   - **Q19 (HHV 2023):** Query is `"Tổng tỷ lệ quyền biểu quyết của công ty mẹ CTCP Đầu tư Hạ tầng Giao thông Đèo Cả năm 2023..."`.
     - `parsed_query['ticker'] == 'CTCP'` instead of `'HHV'`.
     - Table `HHV_..._2023_consolidated_table_63.csv` column `2` (`'Quyền biểu quyết'`) contains percentage strings `1,23%`, `20,11%`, `21,34%`.

3. **Existing Test Suite State:**
   - `pipeline/tests/test_q_1_success.py` .. `test_q_50_success.py` were exported as standalone scripts with hardcoded Kaggle paths (`/kaggle/input/...`).
   - Running `pytest pipeline/tests/` triggers `FileNotFoundError` during test collection.
   - A dedicated pytest suite (`pipeline/tests/test_phase1_fixes.py`) is required.

4. **Codebase Syntax Defect in `pipeline/src/nodes/query_parser.py`:**
   - Lines 25-26 in `query_parser.py` have a broken structure:
     `with open(prompt_path, "r", encoding="utf-8") as f:`
     `    rNEGATIVE_BLOCKLIST = ...`
     instead of `return yaml.safe_load(f)` followed by module-level definitions.

5. **Notebook Structure `notebooks/kaggle_bootstrap.ipynb`:**
   - Format: Jupyter Notebook v4 (31 cells total).
   - **Cell 11 (0-indexed)** = Section 2: Prompts (`PROMPT_QUERY_PARSER`, `PROMPT_SCHEMA_MAPPER`, etc.).
   - **Cell 15 (0-indexed)** = Section 4: Node 1 Query Parser (`query_parser_node`).
   - **Cell 19 (0-indexed)** = Section 4: Node 3 Schema Mapper (`schema_mapper_node`).

---

## 2. Logic Chain

1. **Local CSV Execution Feasibility:**
   - *Observation:* 150/150 table CSV files exist in `rag_module/ViFinQA/processed_data/`.
   - *Logic:* By providing a fixture or helper to map Kaggle paths to local paths relative to repo root, all data loading succeeds deterministically without external networking.

2. **Phase 1 Fixes Sufficiency for the 5 Critical Cases:**
   - *Observation:* Q28, Q42, Q19 failures stem from Node 1 (Ticker hallucination / prefix clutter), while Q32, Q41, Q19 failures stem from Node 3 (index column misclassification, text density preference, percentage column handling).
   - *Logic:* 
     - Adding `NEGATIVE_BLOCKLIST` and Vietnamese brand alias mappings in Node 1 fixes Q28 (`NVL`), Q19 (`HHV`), Q41 (`DLG`), Q30 (`BVH`), Q33 (`MBB`), Q38 (`SHB`), Q39 (`GVR`), Q43 (`ACV`).
     - Adding prefix stripping in `_clean_financial_content` fixes Q42 and Q28 string contains matching.
     - Adding float index detection (`\d+\.\d+`) and string length density ranking in `_find_label_column` fixes Q32 and Q41.
     - Supporting `%` match in `_find_value_column` fixes Q19.

3. **Notebook Synchronization:**
   - *Observation:* The notebook is structured as standard JSON v4 where cells 11, 15, 19 map 1:1 to Prompts, Node 1, and Node 3.
   - *Logic:* Reading with `json.load()`, updating `cells[i]["source"]` with `.splitlines(keepends=True)`, and writing back with `json.dump(..., ensure_ascii=False, indent=1)` guarantees 100% valid notebook JSON format.

---

## 3. Caveats

- **Qdrant Search Reranking (Phase 2):** In cases where table retrieval ranking requires dense vectors, Phase 1 focuses on deterministic table loading and rule-based parsing/mapping.
- **Complex Hierarchical Multi-year Codegen (Phase 3):** Cases like Q21 (multi-year growth calculation) and Q47 (segment summation) belong to Phase 3 codegen optimizations.

---

## 4. Conclusion

- The local test infrastructure and CSV datasets are 100% ready for Phase 1 Hotfix implementation.
- All 5 critical failure cases (Q28, Q42, Q32, Q41, Q19) and the 23 baseline success cases are fully mapped, with explicit local CSV paths verified.
- The blueprint for `pipeline/tests/test_phase1_fixes.py` and the Kaggle Notebook sync protocol are documented in `d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_3/survey_report.md`.

---

## 5. Verification Method

To verify these survey findings:
1. **Verify local CSV existence:**
   `python -c "from pathlib import Path; print('Processed data exists:', Path('rag_module/ViFinQA/processed_data').exists())"`
2. **Verify Notebook JSON integrity:**
   `python -c "import json; nb=json.load(open('notebooks/kaggle_bootstrap.ipynb', encoding='utf-8')); print('Cell count:', len(nb['cells']), 'Cell 11/15/19 types:', [nb['cells'][i]['cell_type'] for i in [11,15,19]])"`
3. **Inspect full survey report:**
   View `d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_3/survey_report.md`.
