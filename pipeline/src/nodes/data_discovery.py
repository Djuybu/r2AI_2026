"""Node 2: Data Discovery Node.
Tìm kiếm bảng dữ liệu tài chính sử dụng Search Engine (run_hybrid_search).
Không sử dụng fallback — chỉ dùng hàm của Search Engine trong search_engine.py.
"""

import re
import time
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict, Any

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config


def _resolve_csv_path(csv_path_str: str, cfg: Config) -> Optional[Path]:
    """Resolve csv_path from search engine result to an actual local file path."""
    if not csv_path_str:
        return None

    p_str = csv_path_str.replace("\\", "/")

    # Try direct path first
    direct = Path(p_str).resolve()
    if direct.exists():
        return direct

    # Try relative from ViFinQA
    idx_fin = p_str.find("ViFinQA")
    if idx_fin != -1:
        relative_part = p_str[idx_fin:]
        repo_root = Path(cfg.DATA_DIR).parent.parent.resolve()

        candidate1 = (repo_root / relative_part).resolve()
        if candidate1.exists():
            return candidate1

        candidate2 = (repo_root / "rag_module" / relative_part).resolve()
        if candidate2.exists():
            return candidate2

    return None


def _load_table_data(file_path: Path) -> Optional[pd.DataFrame]:
    """Load a CSV or Excel file into a DataFrame."""
    try:
        if str(file_path).endswith('.csv'):
            return pd.read_csv(file_path)
        elif str(file_path).endswith(('.xlsx', '.xls')):
            return pd.read_excel(file_path)
    except Exception as e:
        print(f"⚠️ [Data Discovery] Không thể đọc file {file_path.name}: {e}")
    return None


# Canonical search queries for each required table type (used in multi-table mode)
_TABLE_TYPE_QUERIES: Dict[str, str] = {
    "income_statement": "báo cáo kết quả hoạt động kinh doanh lợi nhuận doanh thu",
    "balance_sheet":    "bảng cân đối kế toán tài sản nguồn vốn nợ phải trả",
    "cash_flow":        "báo cáo lưu chuyển tiền tệ dòng tiền hoạt động kinh doanh",
    "notes":            "thuyết minh báo cáo tài chính",
}

def data_discovery_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 2: Tìm kiếm bảng dữ liệu liên quan bằng Search Engine.

    Xây dựng query từ ten_cong_ty + noi_dung (từ parsed_query),
    sử dụng run_hybrid_search() để tìm bảng.
    Không fallback về code tìm kiếm có sẵn.

    Args:
        state: Current AgentState containing 'parsed_query' and 'user_query'
        cfg: System Config instance

    Returns:
        Updated AgentState with 'discovered_tables'.
    """
    cfg = cfg or default_config
    start_time = time.time()

    user_query = state.get("user_query", "")
    parsed_query = state.get("parsed_query", {})

    # Extract fields from parsed_query
    noi_dung = parsed_query.get("noi_dung", "")
    ten_cong_ty = parsed_query.get("ten_cong_ty", "")
    so_nam = parsed_query.get("so_nam", [])
    muc_tieu = parsed_query.get("muc_tieu", "trich_xuat")

    print(f"\n🔍 [Data Discovery] Bắt đầu tìm kiếm dữ liệu...")
    print(f"   - Nội dung: '{noi_dung}'")
    print(f"   - Công ty: '{ten_cong_ty}'")
    print(f"   - Năm: {so_nam}")
    print(f"   - Mục tiêu: {muc_tieu}")

    # Build search query: chỉ bao gồm tên công ty + nội dung
    search_query = f"{ten_cong_ty} {noi_dung}".strip()
    if not search_query:
        search_query = user_query  # Fallback to full query if fields empty

    print(f"   - Search query: '{search_query}'")

    # Import and use Search Engine
    try:
        from rag_module.search_engine import search_by_company_and_content, parse_query as se_parse_query
        import rag_module.search_engine as se

        # Ensure resources are loaded
        se._ensure_resources()

        # Parse report type from query if mentioned explicitly
        report_type = "separate"
        if "hợp nhất" in user_query.lower():
            report_type = "consolidated"
        else:
            report_type = "separate"
        print(f"   - Ticker tìm thấy bằng Local Fallback: {ticker or 'Không tìm thấy'}, Report Type: {report_type}")

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

    # Use LLM-generated RAG search query if available, else fall back to cleaned user query
    rag_search_query = parsed_query.get("rag_search_query", "").strip()
    if not rag_search_query:
        rag_search_query = clean_query_for_search(user_query)
    print(f"   - RAG search query: '{rag_search_query}'")

    # Table types required to answer this question (from query_parser LLM output)
    required_tables = parsed_query.get("required_tables", [])
    is_multi_table = len(required_tables) > 1
    if is_multi_table:
        print(f"   - Multi-table mode: {required_tables}")

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
                if is_multi_table:
                    # --- Multi-table mode: one RAG call per required table type ---
                    for table_type in required_tables:
                        tq = _TABLE_TYPE_QUERIES.get(table_type, rag_search_query)
                        t_results = run_hybrid_search(tq, ticker=ticker, year=y, report_type=report_type)
                        if t_results:
                            best = t_results[0]
                            csv_path_str = best.get("csv_path")
                            if csv_path_str:
                                p_str = csv_path_str.replace("\\", "/")
                                idx_fin = p_str.find("ViFinQA")
                                relative_part = p_str[idx_fin:] if idx_fin != -1 else Path(p_str).name
                                repo_root = Path(cfg.DATA_DIR).parent.parent.resolve()
                                for cand in [
                                    (repo_root / relative_part).resolve(),
                                    (repo_root / "rag_module" / relative_part).resolve(),
                                    Path(p_str).resolve(),
                                ]:
                                    if cand.exists():
                                        key = f"{y}_{table_type}"
                                        matched_table_paths[key] = str(cand)
                                        table_schemas[str(cand)] = get_table_schema(cand)
                                        print(f"   - [{key}]: {cand.name} (RRF: {best.get('rrf_score')})")
                                        break
                        else:
                            print(f"   - [{y}_{table_type}]: RAG không tìm thấy kết quả.")
                    continue  # skip single-table logic below

                # --- Single-table mode (original behaviour) ---
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
                results = run_hybrid_search(rag_search_query, ticker=ticker, year=y, report_type=report_type)
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
                    print(f"   ❌ Không thể resolve đường dẫn file: {best_match.get('csv_path')}")
            else:
                print(f"   ❌ Không tìm thấy kết quả phù hợp.")
        except Exception as e:
            print(f"⚠️ [Data Discovery] Lỗi tra cứu: {e}")
    else:
        # Search year-by-year — pick TOP 1 best match for each year
        for year in so_nam:
            print(f"   - Tra cứu bảng tốt nhất cho năm {year}...")
            try:
                results = search_by_company_and_content(
                    company_name=ten_cong_ty,
                    content=noi_dung,
                    year=str(year),
                    report_type=report_type,
                    top_k=5,
                )
                if results:
                    best_match = results[0]  # Bảng có độ khớp cao nhất của năm đó
                    csv_path = _resolve_csv_path(best_match.get("csv_path", ""), cfg)
                    if csv_path:
                        table_entry = {
                            "csv_path": str(csv_path),
                            "Ten_Bang": best_match.get("Ten_Bang", ""),
                            "rrf_score": best_match.get("rrf_score", 0.0),
                            "Ma_Doanh_Nghiep": best_match.get("Ma_Doanh_Nghiep", ten_cong_ty),
                            "Nam_Tai_Chinh": str(year),
                            "Loai_Bao_Cao": best_match.get("Loai_Bao_Cao", report_type),
                        }
                        all_discovered_tables.append(table_entry)
                        print(f"   🏆 Năm {year} - Bảng có độ khớp CAO NHẤT: {csv_path.name} — {best_match.get('Ten_Bang', '?')} (RRF: {table_entry['rrf_score']:.4f})")
                    else:
                        print(f"   ❌ Năm {year}: Không thể resolve đường dẫn file: {best_match.get('csv_path')}")
                else:
                    print(f"   ❌ Năm {year}: Không tìm thấy kết quả phù hợp.")
            except Exception as e:
                print(f"   ⚠️ Năm {year}: Lỗi tra cứu — {e}")

    latency = time.time() - start_time
    node_latencies = state.get("node_latencies", {})
    node_latencies["data_discovery"] = round(latency, 3)

    if not all_discovered_tables:
        print(f"\n❌ [Data Discovery] Không tìm thấy bảng dữ liệu nào phù hợp.")
        return {
            **state,
            "status": "error",
            "error_message": "Không tìm thấy bảng dữ liệu phù hợp từ Search Engine.",
            "discovered_tables": [],
            "node_latencies": node_latencies,
        }

    print(f"\n📊 [Kết quả - Data Discovery]: Đã chọn {len(all_discovered_tables)} bảng có độ khớp cao nhất.\n")

    return {
        **state,
        "discovered_tables": all_discovered_tables,
        "status": "pending",
        "node_latencies": node_latencies,
    }

