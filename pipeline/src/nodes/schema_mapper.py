"""Node 3: Schema Mapper Node.
Ánh xạ tiêu chí phụ (tieu_chi_phu) sang tên cột thực tế trong bảng dữ liệu.
Nội dung (noi_dung) nằm ở cột đầu tiên nên không cần map.
Sử dụng rule-based matching, không gọi LLM.
"""

import time
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional
from thefuzz import process, fuzz

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config


# Danh sách các cột giá trị phổ biến trong báo cáo tài chính Việt Nam
DEFAULT_VALUE_COLUMNS = [
    "Năm nay", "Năm trước",
    "Số cuối năm", "Số đầu năm",
    "Số cuối kỳ", "Số đầu kỳ",
    "Kỳ này", "Kỳ trước",
]

# Các cột nhãn (cột đầu tiên) phổ biến
LABEL_COLUMNS = [
    "CHÍ TIÊU", "CHỈ TIÊU", "TÀI SẢN", "NGUỒN VỐN",
    "Cột_0", "Mã số", "Chỉ tiêu",
]


def _get_columns_from_table(table: Dict[str, Any]) -> List[str]:
    """Extract column names from a discovered table by reading its CSV file."""
    csv_path = table.get("csv_path", "")
    if not csv_path:
        return []

    try:
        df = pd.read_csv(csv_path, nrows=2)
        return list(df.columns)
    except Exception:
        return []


def _find_label_column(columns: List[str]) -> Optional[str]:
    """Find the label column (cột đầu tiên chứa tên chỉ tiêu)."""
    for c in LABEL_COLUMNS:
        if c in columns:
            return c

    # Fallback: check column index 0
    if columns and not columns[0].replace('.', '').isdigit():
        return columns[0]

    return None


def _find_value_column(columns: List[str], tieu_chi_phu: Optional[str] = None) -> Optional[str]:
    """Find the value column based on tieu_chi_phu or default heuristics."""
    non_label_cols = [c for c in columns if c not in LABEL_COLUMNS]

    if tieu_chi_phu and non_label_cols:
        # 1. Exact or substring match for dates / explicit column criteria
        clean_tcp = str(tieu_chi_phu).strip().lower()
        for col in non_label_cols:
            if clean_tcp in col.strip().lower():
                return col

        # 2. Fuzzy match tieu_chi_phu against actual columns
        match, score = process.extractOne(
            tieu_chi_phu, non_label_cols, scorer=fuzz.token_set_ratio
        )
        if score >= 50:
            return match

    # Default: find first known value column
    for c in DEFAULT_VALUE_COLUMNS:
        if c in columns:
            return c

    # Fallback: pick second column (first non-label column)
    if len(columns) >= 2:
        return columns[1]

    return None


def schema_mapper_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 3: Map tiêu chí phụ sang tên cột thực tế.

    - Nội dung (noi_dung) nằm ở cột đầu tiên → không cần map.
    - Chỉ cần map tiêu_chí_phụ → tên cột giá trị thực tế.
    - Rule-based matching, không gọi LLM.

    Args:
        state: Current AgentState containing 'parsed_query' and 'discovered_tables'
        cfg: Config instance

    Returns:
        Updated AgentState with 'column_mapping'
    """
    cfg = cfg or default_config
    start_time = time.time()

    parsed_query = state.get("parsed_query", {})
    discovered_tables = state.get("discovered_tables", [])
    tieu_chi_phu = parsed_query.get("tieu_chi_phu")

    print(f"\n🔍 [Schema Mapper] Đang ánh xạ tiêu chí → cột thực tế...")
    print(f"   - Tiêu chí phụ: {tieu_chi_phu or '(không có)'}")

    column_mapping: Dict[str, str] = {}

    if not discovered_tables:
        print(f"⚠️ [Schema Mapper] Không có bảng dữ liệu để ánh xạ.")
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["schema_mapper"] = round(latency, 3)
        return {
            **state,
            "column_mapping": {},
            "status": "pending",
            "node_latencies": node_latencies,
        }

    # Read columns from the first discovered table
    first_table = discovered_tables[0]
    columns = _get_columns_from_table(first_table)

    if not columns:
        print(f"⚠️ [Schema Mapper] Không đọc được cột từ bảng: {first_table.get('csv_path')}")
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["schema_mapper"] = round(latency, 3)
        return {
            **state,
            "column_mapping": {},
            "status": "pending",
            "node_latencies": node_latencies,
        }

    print(f"   - Cột trong bảng: {columns}")

    # Find label column (cột đầu tiên)
    label_col = _find_label_column(columns)
    if label_col:
        column_mapping["label_column"] = label_col
        print(f"   - Cột nhãn (chỉ tiêu): '{label_col}'")

    # Find value column based on tieu_chi_phu
    value_col = _find_value_column(columns, tieu_chi_phu)
    if value_col:
        column_mapping["value_column"] = value_col
        print(f"   - Cột giá trị: '{value_col}'")

    # Map all available columns for reference
    column_mapping["all_columns"] = str(columns)

    print(f"\n📊 [Kết quả - Schema Mapper]: {column_mapping}\n")

    latency = time.time() - start_time
    node_latencies = state.get("node_latencies", {})
    node_latencies["schema_mapper"] = round(latency, 3)

    return {
        **state,
        "column_mapping": column_mapping,
        "status": "pending",
        "node_latencies": node_latencies,
    }
