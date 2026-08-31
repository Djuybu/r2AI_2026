"""Node 2: Data Discovery Node.
Tìm kiếm chính xác các bảng dữ liệu bằng Search Engine (search_by_company_and_content)
dựa trên bộ 3 thông tin: ten_cong_ty + so_nam + noi_dung.
"""

import re
import time
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict, Any

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.utils.data_registry import DataRegistry


# Các cột metadata/thông tin chung - dùng để lọc khi trích xuất first_row_values
_METADATA_COLUMNS = {
    "Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "Nam_Tai_Chinh",
    "Loai_Bao_Cao", "Ten_Bang", "Don_Vi_Tinh", "Tep_Nguon"
}


def _extract_table_schema(csv_path: str) -> Dict[str, Any]:
    """Đọc schema (tên cột) và giá trị hàng đầu tiên nếu có cột tên là số.

    Returns:
        Dict với 2 key:
        - table_schema: list[str] — danh sách tên cột
        - first_row_values: dict[str, str] — giá trị hàng đầu tiên (chỉ khi có cột tên số)
    """
    result: Dict[str, Any] = {"table_schema": [], "first_row_values": {}}
    try:
        df = pd.read_csv(csv_path, nrows=1)
        columns = list(df.columns)
        result["table_schema"] = columns

        # Kiểm tra xem có cột nào tên là số (0, 1, 2, 3...) không
        numeric_cols = [c for c in columns if str(c).strip().isdigit()]
        if numeric_cols and not df.empty:
            first_row = df.iloc[0]
            # Trả về giá trị hàng đầu tiên cho các cột không phải metadata
            result["first_row_values"] = {
                str(c): str(first_row[c])
                for c in columns
                if c not in _METADATA_COLUMNS
            }
    except Exception as e:
        print(f"⚠️ Không đọc được schema từ {csv_path}: {e}")
    return result


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


def _get_processed_data_dir(cfg: Config) -> Optional[Path]:
    """Find processed_data directory across local repo and Kaggle environments."""
    candidates = [
        Path(cfg.BASE_DIR.parent / "rag_module" / "ViFinQA" / "processed_data"),
        Path(__file__).resolve().parents[3] / "rag_module" / "ViFinQA" / "processed_data",
        Path("r2AI_2026/rag_module/ViFinQA/processed_data"),
        Path("rag_module/ViFinQA/processed_data"),
        Path("/kaggle/input/datasets/duymcminh/r2-ai-output/r2AI_data/ViFinQA/processed_data"),
        Path("/kaggle/input/r2-ai-output/r2AI_data/ViFinQA/processed_data"),
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return None


def _find_offline_candidate_tables(
    ticker: str,
    so_nam: List[Any],
    noi_dung: str,
    report_type: Optional[str],
    cfg: Config,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Offline scanner: locate top candidate CSV files directly from local processed_data directory."""
    data_dir = _get_processed_data_dir(cfg)
    if not data_dir or not data_dir.exists():
        return []

    if not ticker:
        return []

    ticker_dir = data_dir / ticker.upper()
    if not ticker_dir.exists() or not ticker_dir.is_dir():
        return []

    year_dirs = []
    if so_nam:
        for y in so_nam:
            yd = ticker_dir / str(y)
            if yd.exists() and yd.is_dir():
                year_dirs.append((str(y), yd))
    if not year_dirs:
        for yd in ticker_dir.iterdir():
            if yd.is_dir():
                year_dirs.append((yd.name, yd))

    tokens = [t.lower() for t in re.findall(r"\w+", noi_dung) if len(t) > 1]
    candidates_with_score = []

    for year_str, yd in year_dirs:
        csv_files = list(yd.glob("**/*.csv"))
        for csv_f in csv_files:
            score = 0.0
            p_lower = str(csv_f).lower()

            if report_type == "consolidated" and "consolidated" in p_lower:
                score += 2.0
            elif report_type == "separate" and "separate" in p_lower:
                score += 2.0

            try:
                sample_df = pd.read_csv(csv_f, nrows=15)
                cols_str = " ".join([str(c) for c in sample_df.columns]).lower()
                cells_str = sample_df.astype(str).to_string().lower()

                for tok in tokens:
                    if tok in cols_str:
                        score += 3.0
                    if tok in cells_str:
                        score += 1.5

                if noi_dung.lower() in cells_str:
                    score += 10.0
            except Exception:
                pass

            candidates_with_score.append((score, year_str, csv_f))

    candidates_with_score.sort(key=lambda x: x[0], reverse=True)

    discovered = []
    seen_paths = set()
    for score, year_str, csv_f in candidates_with_score:
        resolved_p = str(csv_f.resolve())
        if resolved_p not in seen_paths:
            seen_paths.add(resolved_p)
            discovered.append({
                "csv_path": resolved_p,
                "Ten_Bang": csv_f.stem,
                "rrf_score": max(score, 0.1),
                "Ma_Doanh_Nghiep": ticker.upper(),
                "Nam_Tai_Chinh": year_str,
                "Loai_Bao_Cao": report_type or ("consolidated" if "consolidated" in str(csv_f) else "separate"),
            })
            if len(discovered) >= top_k:
                break

    return discovered


def _log_candidates(results: List[Dict[str, Any]], year_label: str = "") -> None:
    """In log chi tiết các ứng viên top-K tìm được từ Search Engine kèm minh chứng khớp cột."""
    prefix = f" (Năm {year_label})" if year_label else ""
    print(f"   📋 Danh sách {len(results)} bảng ứng viên Top-K từ Search Engine{prefix}:")
    for idx, item in enumerate(results, 1):
        p_str = item.get("csv_path", "")
        file_name = Path(p_str).name if p_str else "N/A"
        ten_bang = item.get("Ten_Bang", "N/A")
        rrf = item.get("rrf_score", 0.0)
        dense_r = item.get("dense_rank", "-")
        sparse_r = item.get("sparse_rank", "-")
        matched = item.get("content_matched", False)
        matched_col = item.get("matched_col_name", "")
        matched_sample = item.get("matched_sample", "")

        col_tag = f"Cột '{matched_col}'" if matched_col else "Cột đầu tiên có nghĩa"
        matched_str = f" ✅ [Matched {col_tag}]" if matched else ""
        print(f"      #{idx} RRF: {rrf:.6f} | DenseRank: {dense_r} | SparseRank: {sparse_r}{matched_str}")
        print(f"         File: {file_name}")
        print(f"         Tên bảng: {ten_bang}")
        if matched and matched_sample:
            print(f"         🔍 Minh chứng dòng khớp trong {col_tag}: \"{matched_sample}\"")


def clean_query_content(noi_dung_input: str, ticker: str = "", so_nam: list = None) -> str:
    """Làm sạch chuỗi noi_dung: Loại bỏ tên công ty, mã CK, năm, các từ để hỏi và thông tin thừa
    để đảm bảo Search Engine nhận đúng từ khóa chỉ tiêu cốt lõi (VD: 'Lãi tiền gửi', 'Quỹ khen thưởng, phúc lợi').
    """
    if not noi_dung_input:
        return ""
    text = str(noi_dung_input)
    text = re.sub(r"\([A-Za-z]{2,5}\)", "", text)
    text = re.sub(r"\b20\d{2}\b", "", text)
    if ticker:
        text = re.sub(r"\b" + re.escape(ticker) + r"\b", "", text, flags=re.IGNORECASE)

    patterns = [
        r"là bao nhiêu.*",
        r"bao nhiêu.*",
        r"của công ty mẹ.*",
        r"của ngân hàng.*",
        r"của ctcp.*",
        r"của tập đoàn.*",
        r"của công ty.*",
        r"vào ngày.*",
        r"đến ngày.*",
        r"tại ngày.*",
        r"cuối năm.*",
        r"đầu năm.*",
        r"trong năm.*",
        r"năm.*",
        r"báo cáo tài chính.*",
        r"báo cáo riêng.*",
        r"báo cáo hợp nhất.*",
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE)

    prefix_patterns = [
        r"^\s*tổng\s+số\s+",
        r"^\s*tổng\s+",
        r"^\s*số\s+dư\s+",
        r"^\s*giá\s+trị\s+",
        r"^\s*chỉ\s+tiêu\s+",
    ]
    for pp in prefix_patterns:
        text = re.sub(pp, "", text, flags=re.IGNORECASE)

    cleaned = text.strip(" ,.?:;\t\n")
    return cleaned if len(cleaned) >= 2 else noi_dung_input.strip()


def data_discovery_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 2: Tìm kiếm bảng dữ liệu liên quan bằng Search Engine.

    Sử dụng search_by_company_and_content() dựa trên ten_cong_ty, so_nam, và noi_dung.

    Args:
        state: Current AgentState containing 'parsed_query' and 'user_query'
        cfg: System Config instance

    Returns:
        Updated AgentState with 'discovered_tables' and 'matched_table_path'.
    """
    cfg = cfg or default_config
    start_time = time.time()

    user_query = state.get("user_query", "")
    parsed_query = state.get("parsed_query", {})

    # Extract fields from parsed_query
    ten_cong_ty = parsed_query.get("ten_cong_ty", "")
    so_nam = parsed_query.get("so_nam", [])
    noi_dung_raw = parsed_query.get("noi_dung", "")
    thao_tac = parsed_query.get("thao_tac") or parsed_query.get("muc_tieu", "trich_xuat")

    if not so_nam and isinstance(user_query, str):
        so_nam = re.findall(r"\b(20\d{2})\b", user_query)
    if isinstance(user_query, str) and not ten_cong_ty:
        m_ticker = re.search(r"\b([A-Za-z]{3,5})\b", user_query)
        if m_ticker:
            ten_cong_ty = m_ticker.group(1).upper()

    if not noi_dung_raw:
        noi_dung_raw = user_query if isinstance(user_query, str) else ""

    # Làm sạch noi_dung trước khi truyền vào Search Engine
    noi_dung = clean_query_content(noi_dung_raw, ten_cong_ty, so_nam)

    # Suppressed verbose logs
    
    
    
    

    # Determine report type: mặc định None để tìm kiếm trên CẢ 2 loại báo cáo (consolidated & separate)
    report_type = None
    if isinstance(user_query, str):
        q_lower = user_query.lower()
        if "hợp nhất" in q_lower and "riêng" not in q_lower:
            report_type = "consolidated"
        elif "báo cáo riêng" in q_lower:
            report_type = "separate"

    all_discovered_tables: List[Dict[str, Any]] = []

    # Import Search Engine
    try:
        from rag_module.search_engine import search_by_company_and_content
        import rag_module.search_engine as se

        se._ensure_resources()

        if not so_nam:
            print(f"   - Tra cứu bảng cho công ty '{ten_cong_ty}' và nội dung '{noi_dung}'...")
            results = search_by_company_and_content(
                company_name=ten_cong_ty,
                content=noi_dung,
                raw_query=user_query,
                year=None,
                report_type=report_type,
                top_k=5,
            )
            if not results and report_type is not None:
                results = search_by_company_and_content(
                    company_name=ten_cong_ty,
                    content=noi_dung,
                    raw_query=user_query,
                    year=None,
                    report_type=None,
                    top_k=5,
                )
            if results:
                _log_candidates(results)
                for match in results[:5]:
                    csv_path = _resolve_csv_path(match.get("csv_path", ""), cfg)
                    if csv_path:
                        table_entry = {
                            "csv_path": str(csv_path),
                            "Ten_Bang": match.get("Ten_Bang", ""),
                            "rrf_score": match.get("rrf_score", 0.0),
                            "Ma_Doanh_Nghiep": match.get("Ma_Doanh_Nghiep", ten_cong_ty),
                            "Nam_Tai_Chinh": match.get("Nam_Tai_Chinh", ""),
                            "Loai_Bao_Cao": match.get("Loai_Bao_Cao", ""),
                            "matched_sample": match.get("matched_sample", ""),
                        }
                        if not any(t["csv_path"] == str(csv_path) for t in all_discovered_tables):
                            all_discovered_tables.append(table_entry)
                if all_discovered_tables:
                    best = all_discovered_tables[0]
                    print(f"   🏆 Bảng khớp CAO NHẤT: {Path(best['csv_path']).name} — {best['Ten_Bang']} (RRF: {best['rrf_score']:.6f})")
        else:
            for year in so_nam:
                print(f"   - Tra cứu bảng cho năm {year}...")
                results = search_by_company_and_content(
                    company_name=ten_cong_ty,
                    content=noi_dung,
                    raw_query=user_query,
                    year=str(year),
                    report_type=report_type,
                    top_k=5,
                )
                if not results and report_type is not None:
                    results = search_by_company_and_content(
                        company_name=ten_cong_ty,
                        content=noi_dung,
                        raw_query=user_query,
                        year=str(year),
                        report_type=None,
                        top_k=5,
                    )
                if results:
                    _log_candidates(results, year_label=str(year))
                    for match in results[:5]:
                        csv_path = _resolve_csv_path(match.get("csv_path", ""), cfg)
                        if csv_path:
                            table_entry = {
                                "csv_path": str(csv_path),
                                "Ten_Bang": match.get("Ten_Bang", ""),
                                "rrf_score": match.get("rrf_score", 0.0),
                                "Ma_Doanh_Nghiep": match.get("Ma_Doanh_Nghiep", ten_cong_ty),
                                "Nam_Tai_Chinh": str(year),
                                "Loai_Bao_Cao": match.get("Loai_Bao_Cao", ""),
                                "matched_sample": match.get("matched_sample", ""),
                            }
                            if not any(t["csv_path"] == str(csv_path) for t in all_discovered_tables):
                                all_discovered_tables.append(table_entry)
                    if all_discovered_tables:
                        best = all_discovered_tables[0]
                        print(f"   🏆 Năm {year} - Bảng khớp CAO NHẤT: {Path(best['csv_path']).name} — {best['Ten_Bang']} (RRF: {best['rrf_score']:.6f})")

    except Exception as e:
        print(f"⚠️ [Data Discovery] Lỗi/Không dùng được Search Engine: {e}. Thử quét thư mục offline...")

    # Fallback 1: Offline directory scanner when Search Engine is offline/unavailable
    if not all_discovered_tables and ten_cong_ty:
        try:
            offline_tables = _find_offline_candidate_tables(
                ticker=ten_cong_ty,
                so_nam=so_nam,
                noi_dung=noi_dung,
                report_type=report_type,
                cfg=cfg,
                top_k=5,
            )
            for tbl in offline_tables:
                if not any(t["csv_path"] == tbl["csv_path"] for t in all_discovered_tables):
                    all_discovered_tables.append(tbl)
            if all_discovered_tables:
                print(f"   📂 [Data Discovery] Đã nạp thành công {len(all_discovered_tables)} bảng từ thư mục processed_data offline.")
        except Exception as scan_err:
            print(f"⚠️ [Data Discovery] Offline scanner error: {scan_err}")

    # Fallback 2: DataRegistry if still nothing found
    if not all_discovered_tables:
        try:
            registry = DataRegistry(cfg=cfg)
            matched_path = registry.find_best_match(noi_dung) or registry.find_best_match(ten_cong_ty)
            if matched_path and matched_path.exists():
                all_discovered_tables.append({
                    "csv_path": str(matched_path),
                    "Ten_Bang": matched_path.stem,
                    "rrf_score": 1.0,
                    "Ma_Doanh_Nghiep": ten_cong_ty,
                    "Nam_Tai_Chinh": so_nam[0] if so_nam else "",
                    "Loai_Bao_Cao": report_type,
                })
        except Exception as reg_err:
            print(f"⚠️ [Data Discovery] Registry fallback error: {reg_err}")

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
            "top_k_candidates": [],
            "matched_table_path": None,
            "table_schema": [],
            "first_row_values": {},
            "node_latencies": node_latencies,
        }

    # Extract schema và first_row_values cho tất cả các bảng trong Top 5
    for tbl in all_discovered_tables[:5]:
        schema_info = _extract_table_schema(tbl["csv_path"])
        tbl["table_schema"] = schema_info["table_schema"]
        tbl["first_row_values"] = schema_info["first_row_values"]

    first_table_path = all_discovered_tables[0]["csv_path"]
    first_schema = all_discovered_tables[0].get("table_schema", [])
    first_row_val = all_discovered_tables[0].get("first_row_values", {})

    print(f"\n📊 [Kết quả - Data Discovery]: Đã chọn {len(all_discovered_tables)} bảng có độ khớp cao nhất (Top-K candidates: {min(5, len(all_discovered_tables))}).")
    print(f"   📋 Schema bảng Top 1: {first_schema}")
    if first_row_val:
        print(f"   📋 Giá trị hàng đầu tiên (cột số): {first_row_val}")
    print()

    return {
        **state,
        "discovered_tables": all_discovered_tables,
        "top_k_candidates": all_discovered_tables[:5],
        "matched_table_path": first_table_path,
        "table_schema": first_schema,
        "first_row_values": first_row_val,
        "status": "pending",
        "node_latencies": node_latencies,
    }
