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
        state: Current AgentState containing 'parsed_query'
        cfg: System Config instance

    Returns:
        Updated AgentState with 'matched_table_path', 'table_schema', or 'status'='error'
    """
    cfg = cfg or default_config
    start_time = time.time()

    parsed_query = state.get("parsed_query", {})
    query_file_name = parsed_query.get("file_name")

    registry = DataRegistry(cfg)
    matched_path = registry.find_best_match(query_file_name)

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
