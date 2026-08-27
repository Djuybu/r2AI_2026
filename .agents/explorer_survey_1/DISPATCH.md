## 2026-08-27T16:46:06Z
You are Explorer 1 for the Phase 1 Hotfix & Rule-based survey.

Your working directory: d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_1/
You must read:
- ORIGINAL_REQUEST.md: d:/hobby_project/cocopila/r2AI_2026/.agents/ORIGINAL_REQUEST.md

Your Survey Focus (Node 1 Query Parser & Entity Extraction):
1. Locate and analyze Node 1 implementation (e.g. `pipeline/nodes/query_parser.py`, `pipeline/nodes/entity_resolver.py` or wherever Node 1 code lives) and prompt definitions (e.g. `prompts/query_parser.yaml` or config files).
2. Investigate `TickerEntityResolver` (or entity extraction logic):
   - Check how ticker symbols, company names, and entities are currently resolved.
   - Check where and how `NEGATIVE_BLOCKLIST` should be introduced or updated (to avoid false positive tickers like common words).
   - Check Vietnamese brand alias mapping (e.g. Vietcombank -> VCB, Vinamilk -> VNM, FPT, Hoa Phat -> HPG, etc.).
   - Check `_clean_financial_content` or query preprocessing to strip unnecessary prefixes/suffixes or boilerplate.
   - Check `query_parser.yaml` prompt structure, few-shot examples, or output schema.
3. Identify exact file paths, line numbers, function signatures, data structures, and edge cases.
4. Record your findings in `d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_1/survey_report.md` and write a soft `handoff.md`.
5. Send a message to your parent when done with the path to your report.

Strict constraints:
- Do NOT write or edit source code files. You are strictly read-only.
- All report files MUST be written only to your working directory `d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_1/`.
