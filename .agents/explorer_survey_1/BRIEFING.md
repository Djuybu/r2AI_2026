# BRIEFING — 2026-08-27T17:00:00Z

## Mission
Survey Node 1 Query Parser & Entity Extraction (TickerEntityResolver, NEGATIVE_BLOCKLIST, VN brand alias mapping, prompt templates, query preprocessing) for Phase 1 Hotfix & Rule-based improvements.

## 🔒 My Identity
- Archetype: explorer
- Roles: investigator, analyzer, reporter
- Working directory: d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_1/
- Original parent: 95d69bdf-65be-46d8-9a66-b831b5075d3e
- Milestone: Phase 1 Hotfix & Rule-based Survey (Node 1)

## 🔒 Key Constraints
- Read-only investigation — do NOT implement or edit source code
- Write outputs only to working directory: d:/hobby_project/cocopila/r2AI_2026/.agents/explorer_survey_1/

## Current Parent
- Conversation ID: 95d69bdf-65be-46d8-9a66-b831b5075d3e
- Updated: 2026-08-27T17:00:00Z

## Investigation State
- **Explored paths**:
  - `pipeline/src/nodes/query_parser.py`
  - `pipeline/src/prompts/query_parser.yaml`
  - `rag_module/code_stock.csv`
  - `notebooks/kaggle_bootstrap.ipynb` (Cell 11 & Cell 15)
  - `pipeline/tests/` (50 test cases and error logs)
- **Key findings**:
  - Found syntax errors in `query_parser.py` (lines 25 & 225)
  - Identified priority inversion in `_normalize_company_name` causing incorrect subsidiary/parent ticker collisions (e.g. FTS vs FPT)
  - Identified missing financial abbreviations in `NEGATIVE_BLOCKLIST`
  - Cataloged 90+ VN brand aliases for `ALIAS_TICKER_MAP`
  - Found wrong few-shot in `query_parser.yaml` (Chứng khoán FPT -> FPT)
  - Identified state synchronization gap (`parsed_json["ticker"]` vs `parsed_json["ten_cong_ty"]`)
  - Identified out-of-sync notebook cells (Cell 11 & 15)
- **Unexplored areas**: None for Node 1 survey.

## Key Decisions Made
- Completed detailed investigation report (`survey_report.md`) and soft handoff report (`handoff.md`).

## Artifact Index
- `DISPATCH.md` — Dispatch log
- `BRIEFING.md` — Situational awareness
- `progress.md` — Progress tracker
- `survey_report.md` — Comprehensive Node 1 survey report
- `handoff.md` — Structured 5-component handoff report
