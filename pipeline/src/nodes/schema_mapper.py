"""Node 3: Schema Mapper Node.
Ánh xạ tiêu chí phụ (tieu_chi_phu) sang tên cột thực tế trong bảng dữ liệu.
Phân tích schema bảng: useful_columns (các cột giá trị) + sub_sections (danh mục con).
Nội dung (noi_dung) nằm ở cột đầu tiên nên không cần map.
"""

import time
import yaml
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

from thefuzz import process, fuzz
from langchain_core.messages import SystemMessage, HumanMessage

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.llm_provider import get_llm
from pipeline.src.utils.json_repair import safe_parse_json


# Danh sách các cột giá trị phổ biến trong báo cáo tài chính Việt Nam
DEFAULT_VALUE_COLUMNS = [
    "Năm nay", "Năm trước",
    "Số cuối năm", "Số đầu năm",
    "Số cuối kỳ", "Số đầu kỳ",
    "Kỳ này", "Kỳ trước",
]

# Các cột metadata/thông tin chung ở đầu file CSV
METADATA_HEADER_COLUMNS = [
    "Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "Nam_Tai_Chinh",
    "Loai_Bao_Cao", "Ten_Bang", "Don_Vi_Tinh", "Tep_Nguon"
]

# Ưu tiên các tên cột nhãn tiếng Việt rõ ràng
KNOWN_LABEL_COLUMNS = [
    "CHÍ TIÊU", "CHỈ TIÊU", "TÀI SẢN", "NGUỒN VỐN",
    "Cột_0", "Chỉ tiêu", "Mã số", "STT"
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
    """Find the label column (cột đầu tiên chứa tên chỉ tiêu tài chính)."""
    # 1. Kiểm tra các cột có tên nhãn tiếng Việt rõ ràng
    for c in KNOWN_LABEL_COLUMNS:
        if c in columns:
            return c

    # 2. Lấy cột đầu tiên KHÔNG thuộc danh sách metadata chung
    for c in columns:
        if c not in METADATA_HEADER_COLUMNS:
            return c

    return columns[0] if columns else None


def _find_value_column(columns: List[str], label_col: Optional[str] = None, tieu_chi_phu: Optional[str] = None) -> Optional[str]:
    """Find the value column based on tieu_chi_phu or default heuristics."""
    # Lọc ra các cột nằm SAU label_col và KHÔNG thuộc metadata
    label_idx = columns.index(label_col) if label_col and label_col in columns else -1
    
    value_candidate_cols = []
    for idx, c in enumerate(columns):
        if c in METADATA_HEADER_COLUMNS or c == label_col:
            continue
        if idx > label_idx or label_idx == -1:
            value_candidate_cols.append(c)

    if tieu_chi_phu and value_candidate_cols:
        # 1. Exact or substring match for dates / explicit column criteria
        clean_tcp = str(tieu_chi_phu).strip().lower()
        for col in value_candidate_cols:
            if clean_tcp in col.strip().lower():
                return col

        # 2. Fuzzy match tieu_chi_phu against actual value columns
        match, score = process.extractOne(
            tieu_chi_phu, value_candidate_cols, scorer=fuzz.token_set_ratio
        )
        if score >= 50:
            return match

    # Default: find first known value column
    for c in DEFAULT_VALUE_COLUMNS:
        if c in value_candidate_cols:
            return c

    # Fallback: pick first numeric value column available
    if value_candidate_cols:
        return value_candidate_cols[0]

    return None


# ─────────────────────────────────────────────────────────────
# Schema Analysis: useful_columns & sub_sections
# ─────────────────────────────────────────────────────────────

def _extract_useful_columns(
    df: pd.DataFrame,
    label_col: Optional[str],
    metadata_cols: Set[str],
) -> List[Dict[str, str]]:
    """Xác định các cột giá trị hữu dụng (chứa chủ yếu dữ liệu số).

    Xử lý cột có tên là số ('0', '1', '2',...): duyệt các hàng đầu tiên
    để tìm tên thực sự của cột.

    Returns:
        List[{"column_name": str, "column_description": str}]
    """
    useful = []
    all_columns = list(df.columns)

    for col in all_columns:
        # Bỏ qua metadata và label column
        if col in metadata_cols or col == label_col:
            continue

        # Kiểm tra xem cột có chứa chủ yếu dữ liệu số không
        numeric_vals = pd.to_numeric(df[col], errors="coerce")
        non_null_count = df[col].notna().sum()
        if non_null_count == 0:
            continue
        numeric_ratio = numeric_vals.notna().sum() / non_null_count
        if numeric_ratio < 0.5:
            continue

        # Xác định tên cột thực sự
        col_name = str(col)
        if col_name.strip().isdigit():
            # Cột tên là số → duyệt các hàng đầu để tìm tên thực
            resolved_parts = []
            for row_idx in range(min(5, len(df))):
                cell_val = df.iloc[row_idx][col]
                if pd.notna(cell_val):
                    cell_str = str(cell_val).strip()
                    if not cell_str or cell_str.lower() in ["nan", "none", "null", "n/a", "-", "—"]:
                        continue
                    # Nếu giá trị không phải số thuần → là header text
                    try:
                        float(cell_str.replace(",", "").replace(".", ""))
                        break  # Gặp số → dừng duyệt
                    except ValueError:
                        resolved_parts.append(cell_str)
                else:
                    continue
            if resolved_parts:
                col_name = " - ".join(resolved_parts)
            # Nếu không tìm được tên, giữ nguyên tên số

        useful.append({
            "column_name": col_name,
            "column_description": "",
        })

    return useful


def _extract_sub_sections(
    df: pd.DataFrame,
    label_col: Optional[str],
    metadata_cols: Set[str],
) -> List[Dict[str, Any]]:
    """Phát hiện các danh mục con (sub-sections) trong bảng tài chính.

    Danh mục con được phân cách bởi các hàng trống (hàng mà label_col rỗng).
    Section header = hàng có label_col không rỗng, được ngăn cách bởi hàng trống phía trước.

    Returns:
        List[{"section_name": str, "range": [int, int], "total_value": float|None}]
    """
    if not label_col or label_col not in df.columns:
        return []

    # Xác định các cột giá trị (không phải metadata, không phải label)
    value_cols = [c for c in df.columns if c not in metadata_cols and c != label_col]
    if not value_cols:
        return []

    sections = []
    section_header_rows = []

    # Duyệt để tìm section header rows
    prev_was_empty = False
    for idx in range(len(df)):
        label_val = df.iloc[idx][label_col]
        is_label_empty = pd.isna(label_val) or str(label_val).strip() == ""

        if not is_label_empty and prev_was_empty:
            # Đây là section header: label_col có giá trị, hàng trước rỗng
            label_text = str(label_val).strip()

            # Tìm total_value: cột value đầu tiên có giá trị số ở hàng này
            total_value = None
            for vc in value_cols:
                cell = df.iloc[idx][vc]
                if pd.notna(cell):
                    try:
                        cell_str = str(cell).strip().replace(",", "")
                        if cell_str.startswith("(") and cell_str.endswith(")"):
                            cell_str = "-" + cell_str[1:-1].strip()
                        total_value = float(cell_str)
                        break
                    except (ValueError, TypeError):
                        continue

            section_header_rows.append({
                "row_idx": idx,
                "section_name": label_text,
                "total_value": total_value,
            })

        prev_was_empty = is_label_empty

    # Tính range cho mỗi section
    for i, header in enumerate(section_header_rows):
        start = header["row_idx"] + 1
        if i + 1 < len(section_header_rows):
            end = section_header_rows[i + 1]["row_idx"] - 1
        else:
            end = len(df) - 1

        # Cắt bỏ các hàng trống ở cuối range
        while end >= start:
            val = df.iloc[end][label_col]
            if pd.isna(val) or str(val).strip() == "":
                end -= 1
            else:
                break

        if start <= end:
            sections.append({
                "section_name": header["section_name"],
                "range": [start, end],
                "total_value": header["total_value"],
            })

    return sections


def _enrich_column_descriptions(
    cfg: Config,
    useful_columns: List[Dict[str, str]],
    table_name: str,
) -> List[Dict[str, str]]:
    """Gọi LLM để sinh mô tả ngắn gọn cho từng cột giá trị.

    Fallback: nếu LLM fail, giữ column_description rỗng.
    """
    if not useful_columns:
        return useful_columns

    try:
        # Load prompt template
        prompt_path = cfg.get_prompt_path("schema_mapper.yaml")
        if not prompt_path.exists():
            print(f"⚠️ [Schema Mapper] Prompt file not found: {prompt_path}")
            return useful_columns

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_data = yaml.safe_load(f)

        system_prompt = prompt_data.get("system_prompt", "")
        user_template = prompt_data.get("user_prompt_template", "")

        col_names = [c["column_name"] for c in useful_columns]
        user_content = user_template.format(
            table_name=table_name,
            columns=", ".join(col_names),
        )

        llm = get_llm(cfg=cfg, temperature=0.0)
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])

        raw_text = response.content if isinstance(response.content, str) else str(response.content)
        parsed = safe_parse_json(raw_text)

        # parsed có thể là list hoặc dict chứa list
        descriptions_list = parsed if isinstance(parsed, list) else parsed.get("columns", [])

        # Map descriptions back vào useful_columns
        desc_map = {}
        for item in descriptions_list:
            if isinstance(item, dict):
                desc_map[item.get("column_name", "")] = item.get("column_description", "")

        for col in useful_columns:
            if col["column_name"] in desc_map:
                col["column_description"] = desc_map[col["column_name"]]

        print(f"   ✅ [Schema Mapper] LLM đã sinh mô tả cho {len(desc_map)} cột.")

    except Exception as e:
        print(f"   ⚠️ [Schema Mapper] LLM enrichment failed: {e}. Giữ descriptions rỗng.")

    return useful_columns


def schema_mapper_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 3: Map tiêu chí phụ sang tên cột thực tế + phân tích schema bảng.

    - Nội dung (noi_dung) nằm ở cột đầu tiên → không cần map.
    - Map tiêu_chí_phụ → tên cột giá trị thực tế (rule-based).
    - Phân tích schema: useful_columns + sub_sections.
    - Gọi LLM để sinh mô tả cột (optional enrichment).

    Args:
        state: Current AgentState containing 'parsed_query' and 'discovered_tables'
        cfg: Config instance

    Returns:
        Updated AgentState with 'column_mapping' and 'schema'
    """
    cfg = cfg or default_config
    start_time = time.time()

    parsed_query = state.get("parsed_query", {})
    discovered_tables = state.get("discovered_tables", [])
    tieu_chi_phu = parsed_query.get("tieu_chi_phu")

    print(f"\n🔍 [Schema Mapper] Đang ánh xạ tiêu chí → cột thực tế...")
    print(f"   - Tiêu chí phụ: {tieu_chi_phu or '(không có)'}")

    column_mapping: Dict[str, str] = {}
    schema: Dict[str, Any] = {"useful_columns": [], "sub_sections": []}

    if not discovered_tables:
        print(f"⚠️ [Schema Mapper] Không có bảng dữ liệu để ánh xạ.")
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["schema_mapper"] = round(latency, 3)
        return {
            **state,
            "column_mapping": {},
            "schema": schema,
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
            "schema": schema,
            "status": "pending",
            "node_latencies": node_latencies,
        }

    print(f"   - Cột trong bảng: {columns}")

    # ── Column Mapping (logic cũ giữ nguyên) ──
    # Find label column (cột đầu tiên)
    label_col = _find_label_column(columns)
    if label_col:
        column_mapping["label_column"] = label_col
        print(f"   - Cột nhãn (chỉ tiêu): '{label_col}'")

    # Find value column based on tieu_chi_phu and label_col
    value_col = _find_value_column(columns, label_col, tieu_chi_phu)
    if value_col:
        column_mapping["value_column"] = value_col
        print(f"   - Cột giá trị: '{value_col}'")

    # Map all available columns for reference
    column_mapping["all_columns"] = str(columns)

    print(f"\n📊 [Kết quả - Schema Mapper - Column Mapping]: {column_mapping}")

    # ── Schema Analysis (logic mới) ──
    csv_path = first_table.get("csv_path", "")
    table_name = first_table.get("Ten_Bang", Path(csv_path).stem if csv_path else "unknown")
    metadata_set = set(METADATA_HEADER_COLUMNS)

    try:
        df_full = pd.read_csv(csv_path)
        print(f"\n📐 [Schema Mapper] Đang phân tích schema bảng ({len(df_full)} hàng)...")

        # 1. Extract useful columns
        useful_columns = _extract_useful_columns(df_full, label_col, metadata_set)
        print(f"   - Cột giá trị hữu dụng ({len(useful_columns)}): {[c['column_name'] for c in useful_columns]}")

        # 2. Extract sub-sections
        sub_sections = _extract_sub_sections(df_full, label_col, metadata_set)
        print(f"   - Danh mục con ({len(sub_sections)}):")
        for sec in sub_sections[:5]:  # Log tối đa 5 section
            total_str = f"{sec['total_value']}" if sec['total_value'] is not None else "N/A"
            print(f"     • {sec['section_name']} (range: {sec['range']}, total: {total_str})")
        if len(sub_sections) > 5:
            print(f"     ... và {len(sub_sections) - 5} section khác")

        # 3. Enrich column descriptions via LLM
        useful_columns = _enrich_column_descriptions(cfg, useful_columns, table_name)

        schema = {
            "useful_columns": useful_columns,
            "sub_sections": sub_sections,
        }

        print(f"\n📊 [Kết quả - Schema Mapper - Schema Analysis]:")
        for col in useful_columns:
            desc = col['column_description'] or '(chưa có mô tả)'
            print(f"   📋 Cột '{col['column_name']}': {desc}")

    except Exception as e:
        print(f"⚠️ [Schema Mapper] Lỗi phân tích schema: {e}. Tiếp tục với schema rỗng.")

    latency = time.time() - start_time
    node_latencies = state.get("node_latencies", {})
    node_latencies["schema_mapper"] = round(latency, 3)

    print(f"\n⏱️ [Schema Mapper] Hoàn thành trong {latency:.3f}s\n")

    return {
        **state,
        "column_mapping": column_mapping,
        "schema": schema,
        "status": "pending",
        "node_latencies": node_latencies,
    }
