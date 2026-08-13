"""Node 2: Data Discovery Node.
Locates target data files from workspace data/ or Kaggle /kaggle/input/ datasets.
"""

import time
from pathlib import Path
from typing import Optional

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.utils.data_registry import DataRegistry, get_table_schema


def data_discovery_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 2: Discover matching data file and extract metadata schema.
    
    Args:
        state: Current AgentState containing 'parsed_query' and 'user_query'
        cfg: System Config instance

    Returns:
        Updated AgentState with 'matched_table_path', 'table_schema', or 'status'='error'
    """
    cfg = cfg or default_config
    start_time = time.time()

    user_query = state.get("user_query", "")
    parsed_query = state.get("parsed_query", {})
    query_file_name = parsed_query.get("file_name")

    matched_path = None

    print(f"🔍 [Data Discovery] Đang tìm kiếm file cho từ khóa: '{query_file_name or 'Trống'}'...")

    # Try hybrid search first using search_engine from rag_module
    try:
        from rag_module.search_engine import run_hybrid_search
        print(f"💭 [Tư duy - Data Discovery]: Thử tìm kiếm bằng RAG Hybrid Search (Qdrant + BM25) cho câu hỏi: '{user_query}'")
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
        print(f"💭 [Tư duy - Data Discovery]: Sử dụng DataRegistry (Fuzzy/Exact matching trên tên file) cho: '{query_file_name}'")
        registry = DataRegistry(cfg)
        matched_path = registry.find_best_match(query_file_name)

    if matched_path:
        print(f"📊 [Kết quả - Data Discovery]: Tìm thấy file phù hợp: {matched_path}\n")
    else:
        print(f"❌ [Kết quả - Data Discovery]: Không tìm thấy file dữ liệu nào phù hợp.\n")

    latency = time.time() - start_time
    node_latencies = state.get("node_latencies", {})
    node_latencies["data_discovery"] = round(latency, 3)

    if not matched_path:
        return {
            **state,
            "status": "error",
            "error_message": f"Không tìm thấy tệp dữ liệu phù hợp cho: '{query_file_name or 'yêu cầu'}' trong thư mục data/ hoặc /kaggle/input/",
            "node_latencies": node_latencies,
        }

    try:
        schema = get_table_schema(matched_path)
        return {
            **state,
            "matched_table_path": str(matched_path),
            "table_schema": schema,
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
