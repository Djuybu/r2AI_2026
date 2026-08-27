# Progress — Milestone 1: Node 1 Query Parser & Entity Extraction Hotfix

Last visited: 2026-08-27T16:57:00Z

## Status
- [x] Initialized DISPATCH.md and BRIEFING.md
- [x] Read ORIGINAL_REQUEST.md, PROJECT.md, and Explorer Survey 1 Report
- [x] Inspect existing `pipeline/src/nodes/query_parser.py` and `pipeline/src/prompts/query_parser.yaml`
- [x] Implement syntax error fix and enhanced logic in `pipeline/src/nodes/query_parser.py`
  - Fixed syntax corruption at lines 25 and 225
  - Added expanded `NEGATIVE_BLOCKLIST` (49 terms)
  - Added rich `ALIAS_TICKER_MAP` (162 brand/colloquial mappings)
  - Updated `_normalize_company_name` resolution precedence: (1) blocklist filter, (2) parentheses ticker `(TICKER)`, (3) brand alias map, (4) stock name registry, (5) standalone uppercase word, (6) LLM fallback
  - Updated `_clean_financial_content` with full prefix and question noise strip patterns
  - Synchronized `parsed_json["ticker"]` and `parsed_json["ten_cong_ty"]`
- [x] Update `pipeline/src/prompts/query_parser.yaml`
  - Added CRITICAL NEGATIVE RULES
  - Corrected few-shot for `CTCP Chứng khoán FPT` -> `ticker: "FTS"`
  - Added few-shot examples for Q19, Q42, Q28
- [x] Run Python verification and unit test suite
  - Executed `.agents/worker_m1/test_m1_verification.py` -> 100% PASS
- [x] Write handoff report and notify parent
