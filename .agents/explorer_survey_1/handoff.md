# Handoff Report: Phase 1 Hotfix Survey (Node 1 Query Parser & Entity Extraction)

**Agent:** explorer_survey_1  
**Target:** orchestrator_1 / implementer agent  
**Report Type:** Soft Handoff (Investigation & Survey Complete)  
**Date:** 2026-08-27  

---

## 1. Observation

1. **Syntax Error in `pipeline/src/nodes/query_parser.py`**:
   - `python -m py_compile pipeline/src/nodes/query_parser.py` failed with:
     ```
     SyntaxError: (unicode error) 'utf-8' codec can't decode byte 0x91 in position 0: invalid start byte (line 225)
     ```
   - Line 25 contains broken code where `rNEGATIVE_BLOCKLIST = {` was pasted directly inside `load_query_parser_prompt`, truncating `with open(...)`.
   - Line 225 contains duplicated corrupted text: `return cleaned.strip()ổi\s+như\s+thế\s+nào\??$",`.
2. **Priority Order Bug in `_normalize_company_name`**:
   - In `pipeline/src/nodes/query_parser.py` lines 145–158, step 2 checks `re.findall(r"\b[A-Za-z]{3,5}\b", user_query)` against `all_tickers` BEFORE step 3 matches company names from `code_stock.csv`.
   - For query `"Chi phí lương... của công ty mẹ CTCP Chứng khoán FPT trong năm 2021..."` (Q8), the word `FPT` was matched as ticker `FPT` instead of resolving the company name `"CTCP Chứng khoán FPT"` to `FTS`.
3. **State Ticker Desynchronization in `parse_query_node`**:
   - In `pipeline/src/nodes/query_parser.py` lines 365–375, `parsed_json["ticker"] = ticker_val` preserves the raw LLM output (e.g. `'CTCP'` for Q28/Q19), while only `parsed_json["ten_cong_ty"]` receives the normalized ticker.
4. **Outdated/Erroneous Prompt Few-Shot**:
   - `pipeline/src/prompts/query_parser.yaml` lines 29–31 maps `"CTCP Chứng khoán FPT"` -> `{"ticker": "FPT", ...}`, which teaches the LLM the wrong ticker symbol.
5. **Kaggle Notebook Out-of-Sync**:
   - `notebooks/kaggle_bootstrap.ipynb` Cell 15 does not contain `NEGATIVE_BLOCKLIST` or `ALIAS_TICKER_MAP`.
   - Cell 11 contains outdated few-shot examples.

---

## 2. Logic Chain

1. From **Observation 1**: The syntax and merge corruption in `query_parser.py` makes importing or executing Node 1 fail in any test script (`test_phase1_fixes.py` or unit tests). Therefore, fixing syntax in `load_query_parser_prompt` and `_clean_financial_content` is the foundational prerequisite.
2. From **Observation 2**: Matching standalone uppercase words before full company names causes sub-brands or subsidiaries (like *Chứng khoán FPT*, *Điện lực Gelex*, *Masan Consumer*) that contain the parent ticker name to be resolved to the parent ticker rather than the specific entity ticker. Placing explicit parentheses matching `(TICKER)` and brand/company name matching ahead of word scanning resolves this.
3. From **Observation 3**: When `parsed_json["ticker"]` and `parsed_json["ten_cong_ty"]` diverge, downstream components or logging that rely on `ticker` receive the un-normalized string (such as `"CTCP"`), causing cascading errors. Synchronizing both fields to `_normalize_company_name(...)` ensures consistent downstream behavior.
4. From **Observation 4 & 5**: The prompt few-shot error directly biases the LLM. Updating both `pipeline/src/prompts/query_parser.yaml` and Notebook Cell 11 eliminates hallucinated and mislabeled outputs.

---

## 3. Caveats

1. **LLM Temperature Sensitivity**: If running with LLM enabled, small models like Qwen 2.5/3.5 2B may occasionally hallucinate unless negative rules and schema enforcement are strictly embedded in the system prompt.
2. **Local CSV Execution**: Per user constraint, testing must NOT use Qdrant DB. All unit/integration tests must resolve against local CSV files in `rag_module/ViFinQA/processed_data/` and `rag_module/code_stock.csv`.

---

## 4. Conclusion

- Node 1 requires a self-contained hotfix covering:
  1. Syntax fixes in `pipeline/src/nodes/query_parser.py` (lines 25 and 225).
  2. Expanded `NEGATIVE_BLOCKLIST` (40+ financial and corporate abbreviations).
  3. Expanded `ALIAS_TICKER_MAP` (90+ Vietnamese brand entries).
  4. Correct resolution priority: `(Parentheses)` -> `Brand Alias` -> `Company Name (Longest)` -> `Standalone Word` -> `LLM Input`.
  5. Sync `state["parsed_query"]["ticker"]` and `state["parsed_query"]["ten_cong_ty"]`.
  6. Prompt correction in `pipeline/src/prompts/query_parser.yaml`.
  7. Notebook sync in `notebooks/kaggle_bootstrap.ipynb` Cells 11 and 15.

---

## 5. Verification Method & Remaining Work

### Verification Command:
```bash
python -m py_compile pipeline/src/nodes/query_parser.py
python -c "from pipeline.src.nodes.query_parser import _normalize_company_name; print(_normalize_company_name('CTCP', 'Tổng phải thu ngắn hạn khác của CTCP Tập đoàn Đầu tư Địa ốc No Va 2016'))"
```
Expected output: `NVL`

### Remaining Work for Implementer:
1. Apply the proposed fixes to `pipeline/src/nodes/query_parser.py`.
2. Update `pipeline/src/prompts/query_parser.yaml`.
3. Synchronize Cell 11 and Cell 15 in `notebooks/kaggle_bootstrap.ipynb`.
4. Include Node 1 tests in `pipeline/tests/test_phase1_fixes.py`.
