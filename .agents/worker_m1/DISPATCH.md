## 2026-08-27T16:51:41Z
You are Worker 1 implementing Milestone 1: Node 1 Query Parser & Entity Extraction Hotfix.

Your working directory: d:/hobby_project/cocopila/r2AI_2026/.agents/worker_m1/
You must read:
- ORIGINAL_REQUEST.md: d:/hobby_project/cocopila/r2AI_2026/.agents/ORIGINAL_REQUEST.md
- PROJECT.md: d:/hobby_project/cocopila/r2AI_2026/PROJECT.md
- Explorer Survey 1 Report: d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_1/survey_report.md

File Ownership (You exclusively own and edit these files):
1. `pipeline/src/nodes/query_parser.py`
2. `pipeline/src/prompts/query_parser.yaml`
Do NOT touch any other files.

Tasks to implement:
1. Fix syntax and merge errors in `pipeline/src/nodes/query_parser.py` (specifically lines 25 and 225 where file was broken / corrupted).
2. Implement expanded `NEGATIVE_BLOCKLIST` with 40+ financial and corporate terms (CTCP, TMCP, TẬP ĐOÀN, CÔNG TY, NGÂN HÀNG, TỔNG CÔNG TY, TNHH, CP, DN, JSC, CORP, CORPORATION, GROUP, BANK, HOLDINGS, SECURITIES, CHỨNG KHOÁN, BẢO HIỂM, BẤT ĐỘNG SẢN, BÁO CÁO, TÀI CHÍNH, BCTC, TCTD, TNDN, TNCN, GTGT, VAMC, CHKQT, CHK, HĐQT, HDQT, TSCĐ, TSCD, SXKD, XDCB, VIỆT NAM, QUỐC TẾ, ĐẦU TƯ, THƯƠNG MẠI, XÂY DỰNG, NĂNG LƯỢNG, VND, USD, EUR, HOSE, HNX, UPCOM, VN30, VNINDEX).
3. Implement `ALIAS_TICKER_MAP` with 90+ Vietnamese brand / colloquial mappings (e.g. Địa ốc No Va / Novaland -> NVL, Đèo Cả -> HHV, Đức Long Gia Lai -> DLG, FPT Telecom -> FOX, Chứng khoán FPT -> FTS, Thế giới di động -> MWG, Vinamilk -> VNM, Hòa Phát -> HPG, Vietcombank -> VCB, Sacombank -> STB, etc. See survey report §3.3 for the complete dictionary).
4. Update `_normalize_company_name` resolution precedence:
   - Reset `company_input = ""` if in `NEGATIVE_BLOCKLIST`.
   - Check explicit parentheses `(TICKER)` in user query against `all_tickers`.
   - Check `ALIAS_TICKER_MAP` sorted by length descending against lower-cased query.
   - Check `name_to_code` sorted by length descending against lower-cased query (both full company name and clean company name without generic corporate prefixes).
   - Check standalone uppercase 3-5 letter words in query against `all_tickers` (excluding `NEGATIVE_BLOCKLIST`).
   - Validate LLM fallback `company_input`.
5. Update `_clean_financial_content`: Strip leading action/measurement prefixes (tốc độ tăng trưởng, tăng trưởng, mức biến động, chênh lệch, so sánh, tính tổng, trích xuất, cho biết, số dư, tổng số, tổng giá trị, khoản, giá trị còn lại của) and trailing question noise (là bao nhiêu, bao nhiêu, thay đổi như thế nào, như thế nào). Ensure `_clean_financial_content` is applied cleanly.
6. Synchronize state: In `parse_query_node`, ensure both `parsed_json["ticker"]` and `parsed_json["ten_cong_ty"]` are set to the resolved ticker.
7. Update `pipeline/src/prompts/query_parser.yaml`: Add negative rules against generic corporate words (CTCP, TMCP, etc.), fix the few-shot example for `CTCP Chứng khoán FPT` -> `ticker: "FTS"`.
8. Run python verification: Execute python tests on Node 1 (importing `parse_query_node`, testing `_normalize_company_name`, `_clean_financial_content` across test cases including Q28, Q42, Q32, Q41, Q19).
