# E2E Test Infra: Cocopila ViFinQA Phase 1 Hotfix

## Test Philosophy
- Opaque-box, requirement-driven, 100% offline with local CSV files. Zero Qdrant / external API dependency.
- Test runner: `pytest pipeline/tests/test_phase1_fixes.py`

## Feature Inventory & Test Coverage
| # | Feature | Requirement | Tier 1 (Unit) | Tier 2 (Boundary) | Tier 3 (Integration) | Tier 4 (Regression) |
|---|---|---|:---:|:---:|:---:|:---:|
| F1 | TickerEntityResolver Precedence | Parentheses -> Alias -> Longest Clean Name -> Word | 5 | 5 | ✓ (Q28, Q19) | ✓ |
| F2 | NEGATIVE_BLOCKLIST | 40+ terms blocked from ticker assignment | 5 | 5 | ✓ (Q28, Q19) | ✓ |
| F3 | Vietnamese Brand Alias Map | 90+ brand mappings | 8 | 5 | ✓ (Q28, Q19, Q41) | ✓ |
| F4 | Query Content Cleaner | Strip action prefixes and question suffixes | 5 | 5 | ✓ (Q42, Q28) | ✓ |
| F5 | Ticker State Sync | `ticker` == `ten_cong_ty` | 3 | 3 | ✓ (Q19) | ✓ |
| F6 | Query Parser Prompt Fix | Few-shot `FTS` fix + negative rules | 2 | 2 | ✓ | ✓ |
| F7 | STT / Index Column Elimination | 100% removal of STT, float index (`1.0, 2.0`) | 5 | 5 | ✓ (Q32, Q41, Q42) | ✓ |
| F8 | Longest String Label Selection | `max(avg_str_len)` selection | 5 | 5 | ✓ (Q32, Q41, Q19) | ✓ |
| F9 | Value Column Percentage Support | `%`, `phần trăm`, `biểu quyết` matching | 4 | 4 | ✓ (Q19) | ✓ |
| F10 | Safe `.astype(str)` Protection | Guard against float/NaN `TypeError` | 4 | 4 | ✓ (Q41, Q42) | ✓ |
| F11 | 5 Critical Hotfix Cases | Q28 (NVL), Q42 (EIB), Q32 (FPT), Q41 (DLG), Q19 (HHV) | - | - | 5 | - |
| F12 | 23 Baseline Regression Cases | Full coverage across previously successful questions | - | - | - | 23 |

## Test Architecture
- Test file: `pipeline/tests/test_phase1_fixes.py`
- Local data directory: `rag_module/ViFinQA/processed_data/`
- Zero network / Zero Qdrant DB requirement.
