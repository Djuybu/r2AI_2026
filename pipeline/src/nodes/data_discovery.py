"""Node 2: Data Discovery Node.
Locates target data files from workspace data/ or Kaggle /kaggle/input/ datasets.
"""

import re
import time
from pathlib import Path
from typing import Optional, Dict, Any

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.utils.data_registry import DataRegistry, get_table_schema


def extract_years_from_text(text: str) -> list[str]:
    """Extract list of explicit years or year ranges from Vietnamese/English text."""
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    if not years:
        return []
    
    # Check for range indicator words
    text_lower = text.lower()
    is_range = False
    for word in ["từ", "đến", "tới", "-", "to", "through", "thru"]:
        if word in text_lower:
            is_range = True
            break
            
    if is_range and len(years) == 2:
        start_year = min(years)
        end_year = max(years)
        if 0 < end_year - start_year <= 15:
            return [str(y) for y in range(start_year, end_year + 1)]
            
    return [str(y) for y in sorted(list(set(years)))]


def get_available_years_for_ticker(ticker: str, cfg: Config) -> list[str]:
    """Scans filesystem to find available financial statement years for a given ticker."""
    repo_root = Path(cfg.DATA_DIR).parent.parent.resolve()
    p_dir = repo_root / "rag_module" / "ViFinQA" / "processed_data" / ticker
    if not p_dir.exists():
        p_dir = repo_root / "ViFinQA" / "processed_data" / ticker
        
    if p_dir.exists():
        years = [d.name for d in p_dir.iterdir() if d.is_dir() and d.name.isdigit()]
        return sorted(years)
    return []


def clean_query_for_search(query: str) -> str:
    """Removes year-related phrases and ranges to create a stable query for cross-year RAG matching."""
    q = re.sub(r"\b20\d{2}\b", "", query)
    # Remove range indicator words
    for word in ["từ", "đến", "tới", "năm", "các năm", "trong", "gần đây", "gần nhất", "qua"]:
        q = re.sub(rf"\b{word}\b", "", q, flags=re.IGNORECASE)
    # Clean extra spaces
    q = re.sub(r"\s+", " ", q).strip()
    return q


def find_financial_table_locally(ticker: str, year: str, report_type: str, query: str, cfg: Config) -> Optional[Path]:
    """Scans local ticker directories to find the exact financial table matching the query context."""
    import glob
    import pandas as pd
    from thefuzz import fuzz
    
    q_lower = query.lower()
    
    # Financial indicators mapping to report types
    income_statement_keywords = [
        "lợi nhuận", "doanh thu", "doanh số", "giá vốn", "chi phí bán hàng", 
        "chi phí quản lý", "chi phí tài chính", "lợi nhuận gộp", 
        "lợi nhuận sau thuế", "lợi nhuận trước thuế"
    ]
    balance_sheet_keywords = [
        "tài sản", "nợ phải trả", "nợ ngắn hạn", "nợ dài hạn", 
        "vốn chủ sở hữu", "thặng dư vốn", "cân đối kế toán"
    ]
    cash_flow_keywords = [
        "lưu chuyển tiền tệ", "dòng tiền", "tiền và tương đương tiền"
    ]
    
    targets = []
    if any(k in q_lower for k in income_statement_keywords):
        targets = ["BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH", "BÁO CÁO KÊT QUẢ HOAT ĐÔNG KINH DOANH"]
    elif any(k in q_lower for k in balance_sheet_keywords):
        targets = ["BẢNG CÂN ĐỐI KẾ TOÁN", "BẢNG CÂN ĐÔI KẾ TOÁN"]
    elif any(k in q_lower for k in cash_flow_keywords):
        targets = ["BÁO CÁO LƯU CHUYỂN TIỀN TỆ"]
        
    if not targets:
        return None
        
    repo_root = Path(cfg.DATA_DIR).parent.parent.resolve()
    pattern = f"rag_module/ViFinQA/processed_data/{ticker}/{year}/*{report_type}/*.csv"
    files = glob.glob(str(repo_root / pattern))
    if not files:
        pattern = f"ViFinQA/processed_data/{ticker}/{year}/*{report_type}/*.csv"
        files = glob.glob(str(repo_root / pattern))
        
    best_file = None
    best_score = -1
    
    for f in files:
        # Check files that are likely the main tables (often containing _0 or short names)
        try:
            df_sample = pd.read_csv(f, nrows=1)
            if "Ten_Bang" in df_sample.columns:
                title = str(df_sample["Ten_Bang"].iloc[0]).upper()
                for t in targets:
                    score = fuzz.token_set_ratio(t, title)
                    if score > best_score:
                        best_score = score
                        best_file = Path(f)
        except Exception:
            continue
            
    if best_score >= 85:
        return best_file
    return None


def data_discovery_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 2: Discover matching data file and extract metadata schema.
    
    Args:
        state: Current AgentState containing 'parsed_query' and 'user_query'
        cfg: System Config instance

    Returns:
        Updated AgentState with 'matched_table_paths', 'table_schemas', etc.
    """
    cfg = cfg or default_config
    start_time = time.time()

    user_query = state.get("user_query", "")
    parsed_query = state.get("parsed_query", {})
    query_file_name = parsed_query.get("file_name")

    # Try to parse ticker and report type
    ticker = ""
    report_type = "separate"
    
    try:
        import rag_module.search_engine as se
        se._ensure_resources()
        if se._company_map:
            ticker, _, report_type = se.parse_query(user_query, se._company_map)
            print(f"   - Ticker tìm thấy từ RAG: {ticker or 'Không tìm thấy'}, Report Type: {report_type}")
    except Exception as e:
        print(f"⚠️ Search engine import/load failed: {e}")

    # Extract years
    year_list = extract_years_from_text(user_query)
    
    # Resolve relative years like "3 năm gần đây"
    if ticker and not year_list:
        m_recent = re.search(r"(\d+)\s*năm\s*(gần\s*(đây|nhất)|qua)", user_query.lower())
        if m_recent:
            n_years = int(m_recent.group(1))
            available_years = get_available_years_for_ticker(ticker, cfg)
            if available_years:
                year_list = available_years[-n_years:]
                print(f"   - Tự động phân tích '{n_years} năm gần nhất' thành các năm: {year_list}")

    # Clean query for stable RAG matching across different years
    cleaned_search_query = clean_query_for_search(user_query)
    print(f"   - Cleaned search query: '{cleaned_search_query}'")

    matched_table_paths = {}
    table_schemas = {}

    # If we have a ticker and multiple years, search year-by-year
    if ticker and year_list:
        print(f"💭 [Tư duy - Data Discovery]: Tìm kiếm dữ liệu cho {ticker} qua các năm {year_list}...")
        try:
            from rag_module.search_engine import run_hybrid_search
            from thefuzz import fuzz
            
            target_title = None
            
            for idx, y in enumerate(year_list):
                # 1. Try local scan first for high accuracy
                matched_p = find_financial_table_locally(ticker, y, report_type, user_query, cfg)
                if matched_p:
                    matched_table_paths[y] = str(matched_p)
                    table_schemas[str(matched_p)] = get_table_schema(matched_p)
                    print(f"   - Năm {y}: Khớp file bằng Local Statement Scan: {matched_p.name}")
                    if idx == 0:
                        target_title = table_schemas[str(matched_p)].get("Ten_Bang")
                    continue
                
                # 2. Fallback to hybrid search
                results = run_hybrid_search(cleaned_search_query, ticker=ticker, year=y, report_type=report_type)
                if results:
                    best_match = None
                    if idx == 0:
                        best_match = results[0]
                        target_title = best_match.get("Ten_Bang")
                    else:
                        best_score = -1
                        for r in results[:10]:  # Compare top 10 candidates
                            title = r.get("Ten_Bang", "")
                            if title and target_title:
                                score = fuzz.token_sort_ratio(title.lower(), target_title.lower())
                                if score > best_score:
                                    best_score = score
                                    best_match = r
                        
                        # Fallback to rank #1 if no good match is found
                        if not best_match or best_score < 60:
                            best_match = results[0]
                    
                    csv_path_str = best_match.get("csv_path")
                    if csv_path_str:
                        p_str = csv_path_str.replace("\\", "/")
                        idx_fin = p_str.find("ViFinQA")
                        if idx_fin != -1:
                            relative_part = p_str[idx_fin:]
                        else:
                            relative_part = Path(p_str).name

                        repo_root = Path(cfg.DATA_DIR).parent.parent.resolve()
                        candidate1 = (repo_root / relative_part).resolve()
                        candidate2 = (repo_root / "rag_module" / relative_part).resolve()

                        matched_p = None
                        if candidate1.exists():
                            matched_p = candidate1
                        elif candidate2.exists():
                            matched_p = candidate2
                        else:
                            direct_path = Path(p_str).resolve()
                            if direct_path.exists():
                                matched_p = direct_path

                        if matched_p:
                            matched_table_paths[y] = str(matched_p)
                            table_schemas[str(matched_p)] = get_table_schema(matched_p)
                            print(f"   - Năm {y}: Khớp file {matched_p.name} (Tên bảng: {best_match.get('Ten_Bang')}, RRF: {best_match.get('rrf_score')})")
                        else:
                            print(f"   - Năm {y}: Không tìm thấy file trên local: {relative_part}")
                else:
                    print(f"   - Năm {y}: RAG không tìm thấy kết quả phù hợp.")
        except Exception as e:
            print(f"⚠️ Search engine search failed for year-by-year: {e}.")

    # Fallback to single-file matching if year-by-year search failed or wasn't applicable
    matched_path = None
    if not matched_table_paths:
        # Try local scan first for single-file mode
        if ticker:
            year_match = re.search(r"\b(20\d{2})\b", user_query)
            query_year = year_match.group(1) if year_match else "2021"
            matched_path = find_financial_table_locally(ticker, query_year, report_type, user_query, cfg)
            if matched_path:
                print(f"💭 [Tư duy - Data Discovery]: Tìm thấy file bằng Local Statement Scan: {matched_path}")

        if not matched_path:
            print(f"🔍 [Data Discovery] Đang tìm kiếm file duy nhất cho từ khóa: '{query_file_name or 'Trống'}'...")
            try:
                from rag_module.search_engine import run_hybrid_search
                print(f"💭 [Tư duy - Data Discovery]: Thử tìm kiếm bằng RAG Hybrid Search (Qdrant + BM25)")
                results = run_hybrid_search(user_query)
                if results:
                    best_match = results[0]
                    csv_path_str = best_match.get("csv_path")
                    print(f"   - Tìm thấy file khớp nhất từ RAG: {Path(csv_path_str).name} (RRF Score: {best_match.get('rrf_score')})")
                    if csv_path_str:
                        p_str = csv_path_str.replace("\\", "/")
                        idx = p_str.find("ViFinQA")
                        if idx != -1:
                            relative_part = p_str[idx:]
                        else:
                            relative_part = Path(p_str).name

                        repo_root = Path(cfg.DATA_DIR).parent.parent.resolve()
                        candidate1 = (repo_root / relative_part).resolve()
                        candidate2 = (repo_root / "rag_module" / relative_part).resolve()

                        if candidate1.exists():
                            matched_path = candidate1
                        elif candidate2.exists():
                            matched_path = candidate2
                        else:
                            direct_path = Path(p_str).resolve()
                            if direct_path.exists():
                                matched_path = direct_path
                            else:
                                print(f"⚠️ Search engine path not found: {relative_part}")
                else:
                    print("   - RAG Hybrid Search không trả về kết quả.")
            except Exception as e:
                print(f"⚠️ Search engine search failed: {e}. Falling back to DataRegistry.")

            # Fallback to DataRegistry
            if not matched_path:
                print(f"💭 [Tư duy - Data Discovery]: Sử dụng DataRegistry cho: '{query_file_name}'")
                registry = DataRegistry(cfg)
                matched_path = registry.find_best_match(query_file_name)

    latency = time.time() - start_time
    node_latencies = state.get("node_latencies", {})
    node_latencies["data_discovery"] = round(latency, 3)

    if not matched_table_paths and not matched_path:
        return {
            **state,
            "status": "error",
            "error_message": f"Không tìm thấy tệp dữ liệu phù hợp cho yêu cầu.",
            "node_latencies": node_latencies,
        }

    # Prepare final outputs
    if matched_table_paths:
        first_year = sorted(matched_table_paths.keys())[0]
        first_path = matched_table_paths[first_year]
        first_schema = table_schemas[first_path]
        print(f"📊 [Kết quả - Data Discovery]: Tìm thấy {len(matched_table_paths)} file qua các năm.\n")
        return {
            **state,
            "matched_table_paths": matched_table_paths,
            "table_schemas": table_schemas,
            "matched_table_path": first_path,
            "table_schema": first_schema,
            "status": "pending",
            "node_latencies": node_latencies,
        }
    else:
        try:
            schema = get_table_schema(matched_path)
            year_match = re.search(r"\b(20\d{2})\b", matched_path.name)
            year_key = year_match.group(1) if year_match else "default"
            print(f"📊 [Kết quả - Data Discovery]: Tìm thấy file phù hợp: {matched_path}\n")
            return {
                **state,
                "matched_table_path": str(matched_path),
                "matched_table_paths": {year_key: str(matched_path)},
                "table_schema": schema,
                "table_schemas": {str(matched_path): schema},
                "status": "pending",
                "node_latencies": node_latencies,
            }
        except Exception as e:
            return {
                **state,
                "status": "error",
                "error_message": f"Lỗi đọc schema tệp dữ liệu {matched_path.name}: {str(e)}",
                "node_latencies": node_latencies,
            }

