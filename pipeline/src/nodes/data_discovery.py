"""Node 2: Data Discovery Node.
Tìm kiếm bảng dữ liệu tài chính sử dụng Search Engine (search_by_company_and_content).
Không sử dụng fallback — chỉ dùng hàm của Search Engine trong search_engine.py.
Trả về các bảng có độ khớp cao nhất.
"""

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


def data_discovery_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 2: Tìm kiếm bảng dữ liệu liên quan bằng Search Engine.

    Sử dụng search_by_company_and_content() với ten_cong_ty và noi_dung (từ parsed_query).
    Chỉ trả về các bảng có độ khớp cao nhất.

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

    # Import and use Search Engine
    try:
        from rag_module.search_engine import search_by_company_and_content
        import rag_module.search_engine as se

        # Ensure resources are loaded
        se._ensure_resources()

        # Parse report type from query if mentioned explicitly
        report_type = "separate"
        if "hợp nhất" in user_query.lower():
            report_type = "consolidated"

    except Exception as e:
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["data_discovery"] = round(latency, 3)
        return {
            **state,
            "status": "error",
            "error_message": f"Search Engine không khả dụng: {str(e)}",
            "discovered_tables": [],
            "node_latencies": node_latencies,
        }

    # Search for tables and pick the BEST MATCH table(s)
    all_discovered_tables: List[Dict[str, Any]] = []

    if not so_nam:
        # No year specified — search by company & content, pick top 1 best match
        print(f"   - Tra cứu bảng tốt nhất cho công ty '{ten_cong_ty}' và nội dung '{noi_dung}'...")
        try:
            results = search_by_company_and_content(
                company_name=ten_cong_ty,
                content=noi_dung,
                year=None,
                report_type=report_type,
                top_k=5,
            )
            if results:
                best_match = results[0]  # Bảng có độ khớp cao nhất
                csv_path = _resolve_csv_path(best_match.get("csv_path", ""), cfg)
                if csv_path:
                    table_entry = {
                        "csv_path": str(csv_path),
                        "Ten_Bang": best_match.get("Ten_Bang", ""),
                        "rrf_score": best_match.get("rrf_score", 0.0),
                        "Ma_Doanh_Nghiep": best_match.get("Ma_Doanh_Nghiep", ten_cong_ty),
                        "Nam_Tai_Chinh": best_match.get("Nam_Tai_Chinh", ""),
                        "Loai_Bao_Cao": best_match.get("Loai_Bao_Cao", report_type),
                    }
                    all_discovered_tables.append(table_entry)
                    print(f"   🏆 Bảng có độ khớp CAO NHẤT: {csv_path.name} — {table_entry['Ten_Bang']} (RRF: {table_entry['rrf_score']:.4f})")
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

