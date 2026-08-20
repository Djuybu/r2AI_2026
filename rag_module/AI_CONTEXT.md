# AI_CONTEXT.md - ViFinQA RAG Module Architecture

This document is written for future AI assistants. It describes the system
architecture, critical constraints, and the purpose of each file.

---

## System Overview

This codebase implements a Hybrid Search RAG (Retrieval-Augmented Generation)
pipeline for Vietnamese Financial Statements (the ViFinQA dataset).

### Three Phases

**Phase 1 — ETL**
- Reads `financial_statements/*_extracted.txt`
- Parses HTML tables using BeautifulSoup + lxml (NO REGEX — strict rule)
- Attaches metadata: ticker, year, report type, currency unit, table name
- Tracks source line number via `<table` count in raw text (`@line_N` in Tep_Nguon)
- Writes one CSV per sub-table to `processed_data/`

**Phase 2 — Indexing**
- Reads CSVs, builds `build_rich_content_string()`: Vietnamese text with up to
  50 row labels PLUS all data column names (`Ten cac cot: ...`)
- Encodes with `paraphrase-multilingual-MiniLM-L12-v2` (384-dim vectors)
- Configures **Scalar Quantization (INT8)** + optimized HNSW (`m=16`, `ef_construct=100`)
- Upserts to Qdrant local disk DB; triggers optimizer compaction for minimal disk footprint
- Builds BM25Okapi, serializes to `bm25_index.pkl`

**Phase 3 — Retrieval**
- `run_hybrid_search()`: dense (Qdrant with INT8 + `rescore=True`) + sparse (BM25) + RRF fusion
- `search_by_table_name()`: fuzzy-match tables by Ten_Bang (no embedding needed)
- `search_by_column_name()`: fuzzy-match tables by column header (uses col_names)

---

## Critical Constraints

### Qdrant — LOCAL DISK MODE ONLY

```python
client = QdrantClient(path=str(QDRANT_DB_PATH))  # correct
# client = QdrantClient(host="localhost", port=6333)  # wrong — needs Docker
```

Kaggle Notebooks cannot run Docker, so local disk mode is mandatory.

### Scalar Quantization (INT8) & Rescoring

- Quantization reduces vector memory/disk storage by 4x (`float32` -> `int8`).
- During search, `qdrant_search` uses `QuantizationSearchParams(rescore=True, oversampling=2.0)` to re-calculate exact cosine similarity on top candidates, maintaining 99.5%+ recall.

### HTML Parsing — No Regex

Use BeautifulSoup + lxml only. No regex for HTML strings. Enforced in `data_pipeline.py`.

### Qdrant Client API

Requires `qdrant-client >= 1.9.0`.
- `client.query_points(query=vector, ...)` — NOT `client.search()` (removed in v1.7+)
- Results in `.points` attribute.
- `MatchAny(any=[...])` for OR conditions.

---

## File-by-File Reference

### data_pipeline.py

Full ETL + Indexing pipeline.

- Phase 1: reads `*_extracted.txt`, parses HTML, attaches metadata, writes CSVs.
- Phase 2: reads CSVs, builds content strings (row labels + **column names**),
  encodes vectors, upserts to Qdrant with INT8 Quantization, triggers WAL compaction, builds BM25.
- CLI: `python rag_module/data_pipeline.py [--skip-etl] [--run-indexing]`

### search_engine.py

Hybrid search for Kaggle Notebooks. All resources lazy-loaded and cached.

- `run_hybrid_search(query, top_k, ticker, year, report_type)` — main API (Dense INT8+rescore + Sparse BM25 + RRF)
- `search_by_table_name(company, table_name_query, year?, report_type?, top_k)` — fuzzy-match Ten_Bang, no embedding
- `search_by_column_name(company, column_query, year?, report_type?, top_k)` — fuzzy-match col_names, falls back to line_items if col_names empty
- `_resolve_ticker(company)` — company name or ticker string → ticker code
- `parse_query(question, company_map)` — extracts ticker, year, report_type

### eval_retrieval.py

Batch evaluation against `questions/questions.jsonl`.
CLI: `python rag_module/eval_retrieval.py --question-id 4 --show-data`

### code_stock.csv

Ticker → company name mapping. 100 companies.
Columns: `Ma CK` (ticker), `Ten cong ty` (company name).

### qdrant_local_db/

Qdrant vector DB. Collection: `financial_tables`. Dimension: 384. Distance: Cosine. Quantization: INT8 (quantiles=0.99, always_ram=True).

### bm25_index.pkl

Format: `{"bm25": BM25Okapi, "doc_mapping": List[Dict]}`

Each `doc_mapping` entry has: `csv_path`, `Ma_Doanh_Nghiep`, `Nam_Tai_Chinh`,
`Loai_Bao_Cao`, `Ten_Bang`, `line_items`, `col_names` (comma-separated column headers).

---

## Key Data Structures

### Processed CSV Schema (Phase 1 ETL output)

| Column           | Description                                                           |
|------------------|-----------------------------------------------------------------------|
| Ma_Doanh_Nghiep  | Ticker code (e.g. `FPT`)                                              |
| Ten_Doanh_Nghiep | Company name                                                          |
| Nam_Tai_Chinh    | Year as string (e.g. `"2023"`)                                        |
| Loai_Bao_Cao     | `"separate"`, `"consolidated"`, or `"unknown"`                        |
| Ten_Bang         | Table heading + sub-section, e.g. `"BANG CAN DOI KE TOAN_I. Tien"` |
| Don_Vi_Tinh      | Currency unit (e.g. `"VND"`)                                          |
| Tep_Nguon        | Source path + anchor + line, e.g. `file.txt#table_0_0@line_193`      |
| data columns     | Actual Vietnamese column headers as column names                      |

### RRFResult Dict (from run_hybrid_search)

```python
{
    "csv_path":         str,    # absolute path to source CSV
    "rrf_score":        float,  # fused score (higher = better)
    "dense_rank":       int,
    "sparse_rank":      int,
    "Ma_Doanh_Nghiep":  str,
    "Ten_Doanh_Nghiep": str,
    "Nam_Tai_Chinh":    str,
    "Loai_Bao_Cao":     str,
    "Ten_Bang":         str,
    "Don_Vi_Tinh":      str,
    "Tep_Nguon":        str,
    "line_items":       str,    # comma-separated row labels (up to 50)
    "col_names":        str,    # comma-separated column headers (NEW)
    "row_count":        int,
    "col_count":        int,
}
```

### Multi-Table matched_table_paths (pipeline convention)

Single-table question — key is just the year string:
```python
{"2020": "/path/AAA_2020_income.csv", "2021": "/path/AAA_2021_income.csv"}
```

Multi-table question — flat key `"{year}_{table_type}"`:
```python
{
    "2020_income_statement": "/path/AAA_2020_income.csv",
    "2020_cash_flow":        "/path/AAA_2020_cashflow.csv",
    "2021_income_statement": "/path/AAA_2021_income.csv",
    "2021_cash_flow":        "/path/AAA_2021_cashflow.csv",
}
```

`code_generator` and `schema_mapper` use `for key, path in matched_table_paths.items()`
and work with both shapes without modification.

### Query Parser JSON Schema

```json
{
  "file_name": null,
  "rag_search_query": "loi nhuan sau thue ket qua kinh doanh",
  "required_tables": ["income_statement"],
  "query_details": [{"column_name": "...", "operation": "...", "filter": null}],
  "intent": "aggregate"
}
```

- `rag_search_query` — compact keyword phrase for RAG (no company name, no year, no filler).
  Used by `data_discovery_node` as the search query instead of the raw user question.
- `required_tables` — values: `income_statement`, `balance_sheet`, `cash_flow`, `notes`.
  When `len > 1`, multi-table mode triggers in `data_discovery_node`.

---

## Key Design Decisions

**1. Loai_Bao_Cao = "unknown"**
Some companies publish one report per year with no separate/consolidated label.
ETL assigns `"unknown"`. Search uses `MatchAny(any=[report_type, "unknown"])`.

**2. Rich content strings (row labels + column names)**
`build_rich_content_string()` appends both:
- Up to 50 row labels (`Cac chi tieu: ...`) — enables BM25 row-label matching
- All column names (`Ten cac cot: ...`) — enables matching on column headers

**3. Longest-match entity extraction**
`parse_query()` sorts company names by length descending.
Prevents `"FPT"` from shadowing `"CTCP Chung khoan FPT"` → FTS.

**4. Source line tracking**
`Tep_Nguon` format: `file.txt#table_0_0@line_193`
Computed by counting `\n` characters before each `<table` in raw_content.

**5. Sub-table splitting**
Large tables are split at section header rows. `Ten_Bang` format:
`PARENT_TABLE_NAME_SECTION_NAME` using `_` as separator.