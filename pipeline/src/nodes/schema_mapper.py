"""Node 3: Schema Mapper Node.
Duyệt từng cột trong bảng dữ liệu thực tế để xác thực dữ liệu:
Workflow:
1. Truy vấn các cột từ bảng (Data Table)
2. Xác nhận: Số hàng có dữ liệu > Số hàng không có dữ liệu trong cột
3. Lựa chọn các cột thỏa mãn là Useful Columns
4. Tìm tên cột thực sự (Header Resolution khi tên cột là số/unnamed)
5. Đưa ra mô tả ngữ nghĩa cho cột dựa vào tên và nội dung
6. Xác định động cột nhãn (label_column) và cột giá trị (value_column)
7. Xuất và in ra Output JSON chuẩn phục vụ kiểm thử.
"""

import time
import json
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


# Các cột metadata/thông tin chung ở đầu file CSV cần bỏ qua khi phân tích dữ liệu bảng
METADATA_HEADER_COLUMNS = [
    "Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "Nam_Tai_Chinh",
    "Loai_Bao_Cao", "Ten_Bang", "Don_Vi_Tinh", "Tep_Nguon"
]


def _is_cell_empty(val: Any) -> bool:
    """Kiểm tra xem một ô có bị rỗng, null hoặc chứa ký tự không có dữ liệu hay không."""
    if val is None or pd.isna(val):
        return True
    s = str(val).strip()
    return s.lower() in {"", "nan", "none", "null", "n/a", "na", "-", "—", "--", "nil"}


def _is_numeric_value(val: Any) -> bool:
    """Kiểm tra xem một ô có chứa giá trị số (kể cả số âm trong ngoặc, có dấu phân cách) hay không."""
    if _is_cell_empty(val):
        return False
    s = str(val).strip().replace(",", "").replace(".", "").replace(" ", "")
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    if s.startswith("-") or s.startswith("+"):
        s = s[1:]
    return s.isdigit()


def _resolve_column_header(df: pd.DataFrame, col: str) -> str:
    """Xác định tên thực sự của cột.

    Nếu tên cột là chữ rõ ràng -> giữ nguyên.
    Nếu tên cột là số ('0', '1', '2',...) hoặc 'Unnamed:' -> quét các hàng header đầu tiên.
    """
    raw_name = str(col).strip()
    if not raw_name.isdigit() and not raw_name.startswith("Unnamed:"):
        return raw_name

    # 1. Kiểm tra hàng đầu tiên (row 0)
    if len(df) > 0:
        first_cell = df.iloc[0][col]
        if not _is_cell_empty(first_cell):
            first_str = str(first_cell).strip()
            # Nếu chứa chữ hoặc ký tự ngày tháng / năm / đơn vị
            if not _is_numeric_value(first_str) or any(c in first_str for c in ["/", "-", "20", "19"]):
                return first_str

    # 2. Duyệt qua tối đa 5 hàng đầu để tìm văn bản mô tả header
    for row_idx in range(min(5, len(df))):
        cell_val = df.iloc[row_idx][col]
        if not _is_cell_empty(cell_val):
            cell_str = str(cell_val).strip()
            if not _is_numeric_value(cell_str):
                return cell_str

    # Fallback cho cột số 0 thường là cột chỉ tiêu
    if raw_name == "0":
        return "Chỉ tiêu"

    return raw_name


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


# ─────────────────────────────────────────────────────────────
# Workflow Steps: Useful Columns & Dynamic Mapping
# ─────────────────────────────────────────────────────────────

def _extract_useful_columns(
    df: pd.DataFrame,
    label_col: Optional[str] = None,
    metadata_cols: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Duyệt từng cột một trong bảng và xác nhận:
    Số hàng có dữ liệu > Số hàng không có dữ liệu.

    Returns:
        List[Dict] thông tin các useful columns.
    """
    metadata_set = metadata_cols or set(METADATA_HEADER_COLUMNS)
    useful = []
    total_rows = len(df)
    candidate_cols = [c for c in df.columns if c not in metadata_set]

    print(f"   📊 [Workflow Step 1: Truy vấn các cột]")
    print(f"      • Tổng số hàng trong bảng: {total_rows}")
    print(f"      • Các cột dữ liệu cần duyệt ({len(candidate_cols)} cột): {candidate_cols}")

    print(f"\n   🔍 [Workflow Step 2: Xác nhận số hàng có dữ liệu > số hàng không có dữ liệu]")
    for col in candidate_cols:
        series = df[col]
        data_rows = 0
        empty_rows = 0
        numeric_count = 0
        sample_values = []

        for val in series:
            if _is_cell_empty(val):
                empty_rows += 1
            else:
                data_rows += 1
                if _is_numeric_value(val):
                    numeric_count += 1
                if len(sample_values) < 3:
                    sample_values.append(str(val).strip())

        # Điều kiện bắt buộc: Số hàng có dữ liệu > Số hàng không có dữ liệu
        is_useful = data_rows > empty_rows

        if is_useful:
            print(f"      ✅ Cột '{col}': Có dữ liệu = {data_rows}/{total_rows} > Trống = {empty_rows}/{total_rows} -> HỢP LỆ (Useful)")

            # Step 4: Tìm tên cột thực tế
            resolved_name = _resolve_column_header(df, col)

            # Xác định kiểu dữ liệu
            data_type = "numeric" if (data_rows > 0 and numeric_count / data_rows >= 0.5) else "text"

            useful.append({
                "raw_column": str(col),
                "column_name": resolved_name,
                "data_type": data_type,
                "data_rows_count": data_rows,
                "empty_rows_count": empty_rows,
                "sample_values": sample_values,
                "column_description": "",
            })
        else:
            print(f"      ❌ Cột '{col}': Có dữ liệu = {data_rows}/{total_rows} <= Trống = {empty_rows}/{total_rows} -> BỎ QUA (Không đủ dữ liệu)")

    return useful


def _find_label_column(
    useful_columns: List[Dict[str, Any]],
    columns: Optional[List[str]] = None
) -> Optional[str]:
    """Xác định cột nhãn (chứa tên chỉ tiêu tài chính) một cách động:

    Chọn cột dạng 'text' đầu tiên trong danh sách useful_columns.
    """
    if not useful_columns:
        if columns:
            non_meta = [c for c in columns if c not in METADATA_HEADER_COLUMNS]
            return non_meta[0] if non_meta else columns[0]
        return None

    # Tìm cột text đầu tiên
    text_cols = [c for c in useful_columns if c.get("data_type") == "text"]
    if text_cols:
        return text_cols[0]["raw_column"]

    # Fallback cột đầu tiên trong useful_columns
    return useful_columns[0]["raw_column"]


def _find_value_column(
    useful_columns: List[Dict[str, Any]],
    label_col: Optional[str] = None,
    tieu_chi_phu: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> Optional[str]:
    """Xác định cột giá trị một cách động dựa trên tiêu chí phụ và useful_columns."""
    if not useful_columns:
        if columns:
            candidates = [c for c in columns if c not in METADATA_HEADER_COLUMNS and c != label_col]
            return candidates[0] if candidates else None
        return None

    value_candidates = [c for c in useful_columns if c["raw_column"] != label_col]
    if not value_candidates:
        value_candidates = useful_columns

    if tieu_chi_phu and value_candidates:
        clean_tcp = str(tieu_chi_phu).strip().lower()

        # 1. Exact or substring match theo column_name hoặc raw_column hoặc column_description
        for uc in value_candidates:
            if clean_tcp in uc["column_name"].lower() or clean_tcp in uc["raw_column"].lower() or clean_tcp in uc.get("column_description", "").lower():
                return uc["raw_column"]

        # 2. Fuzzy match tiêu chí phụ với các tên cột
        candidate_names = [uc["column_name"] for uc in value_candidates]
        match, score = process.extractOne(
            tieu_chi_phu, candidate_names, scorer=fuzz.token_set_ratio
        )
        if score >= 50:
            for uc in value_candidates:
                if uc["column_name"] == match:
                    return uc["raw_column"]

    # Default: Chọn cột dạng 'numeric' đầu tiên trong các cột ứng viên
    numeric_candidates = [c for c in value_candidates if c.get("data_type") == "numeric"]
    if numeric_candidates:
        return numeric_candidates[0]["raw_column"]

    return value_candidates[0]["raw_column"]


def _extract_sub_sections(
    df: pd.DataFrame,
    label_col: Optional[str],
    metadata_cols: Set[str],
) -> List[Dict[str, Any]]:
    """Phát hiện các danh mục con (sub-sections) trong bảng tài chính."""
    if not label_col or label_col not in df.columns:
        return []

    value_cols = [c for c in df.columns if c not in metadata_cols and c != label_col]
    if not value_cols:
        return []

    sections = []
    section_header_rows = []

    prev_was_empty = False
    for idx in range(len(df)):
        label_val = df.iloc[idx][label_col]
        is_label_empty = pd.isna(label_val) or str(label_val).strip() == ""

        if not is_label_empty and prev_was_empty:
            label_text = str(label_val).strip()

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

    for i, header in enumerate(section_header_rows):
        start = header["row_idx"] + 1
        if i + 1 < len(section_header_rows):
            end = section_header_rows[i + 1]["row_idx"] - 1
        else:
            end = len(df) - 1

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
    useful_columns: List[Dict[str, Any]],
    table_name: str,
) -> List[Dict[str, Any]]:
    """Gọi LLM để sinh mô tả ngắn gọn cho từng cột useful_columns dựa vào tên và nội dung."""
    if not useful_columns:
        return useful_columns

    # Gán mô tả mặc định rõ ràng
    for col in useful_columns:
        c_name = col.get("column_name", "")
        d_type = col.get("data_type", "dữ liệu")
        if not col.get("column_description"):
            if d_type == "numeric":
                col["column_description"] = f"Cột giá trị số '{c_name}' trong bảng {table_name}"
            else:
                col["column_description"] = f"Cột danh mục/chỉ tiêu '{c_name}' trong bảng {table_name}"

    try:
        from pipeline.src.llm_provider import check_vllm_health
        if ("localhost" in cfg.LLM_API_BASE or "127.0.0.1" in cfg.LLM_API_BASE) and not check_vllm_health(cfg.LLM_API_BASE, timeout=1):
            print(f"   ℹ️ [Schema Mapper] vLLM server offline -> Dùng mô tả cấu trúc mặc định.")
            return useful_columns

        prompt_path = cfg.get_prompt_path("schema_mapper.yaml")
        if not prompt_path.exists():
            print(f"   ⚠️ [Schema Mapper] File prompt không tồn tại: {prompt_path}")
            return useful_columns

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_data = yaml.safe_load(f)

        system_prompt = prompt_data.get("system_prompt", "")
        user_template = prompt_data.get("user_prompt_template", "")

        columns_info_lines = []
        for uc in useful_columns:
            samples_str = ", ".join(uc.get("sample_values", [])[:3])
            columns_info_lines.append(
                f"- Cột: '{uc['column_name']}' (Kiểu: {uc['data_type']}, Mẫu: [{samples_str}])"
            )
        columns_info = "\n".join(columns_info_lines)

        user_content = user_template.format(
            table_name=table_name,
            columns_info=columns_info,
        )

        print(f"\n   🤖 [Workflow Step 5: Gọi LLM sinh mô tả cho {len(useful_columns)} cột useful...]")
        llm = get_llm(cfg=cfg, temperature=0.0, timeout=3)
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])

        raw_text = response.content if isinstance(response.content, str) else str(response.content)
        parsed = safe_parse_json(raw_text)

        descriptions_list = parsed if isinstance(parsed, list) else (parsed.get("columns", []) if isinstance(parsed, dict) else [])

        desc_map = {}
        for item in descriptions_list:
            if isinstance(item, dict):
                desc_map[item.get("column_name", "")] = item.get("column_description", "")

        for col in useful_columns:
            c_name = col["column_name"]
            if c_name in desc_map and desc_map[c_name]:
                col["column_description"] = desc_map[c_name]
            else:
                # Kiểm tra fuzzy match với key trong desc_map
                for k, v in desc_map.items():
                    if k and (k in c_name or c_name in k) and v:
                        col["column_description"] = v
                        break

        print(f"   ✅ [Schema Mapper] LLM đã cập nhật mô tả cho các cột thành công.")

    except Exception as e:
        print(f"   ⚠️ [Schema Mapper] LLM enrichment fallback: {e}. Sử dụng mô tả cấu trúc mặc định.")

    return useful_columns


def schema_mapper_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 3: Schema Mapper Node.

    Thực hiện quy trình:
    1. Truy vấn các cột từ bảng
    2. Xác nhận số hàng có dữ liệu > số hàng không có dữ liệu
    3. Lựa chọn các cột useful
    4. Tìm tên cột thực sự
    5. Đưa ra mô tả cho từng cột
    6. Xác định động label_column và value_column
    7. In Output JSON ra console phục vụ kiểm thử.
    """
    cfg = cfg or default_config
    start_time = time.time()

    parsed_query = state.get("parsed_query", {})
    discovered_tables = state.get("discovered_tables", [])
    tieu_chi_phu = parsed_query.get("tieu_chi_phu")

    print(f"\n" + "=" * 65)
    print(f"🔍 [Node 3: SCHEMA MAPPER] Bắt đầu phân tích Schema theo dữ liệu thực tế...")
    print(f"=" * 65)
    print(f"   - Tiêu chí phụ cần tìm: '{tieu_chi_phu or '(không có)'}'")

    column_mapping: Dict[str, Any] = {}
    schema: Dict[str, Any] = {"useful_columns": [], "sub_sections": []}

    if not discovered_tables:
        print(f"   ⚠️ [Schema Mapper] Không có bảng dữ liệu đầu vào để ánh xạ.")
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

    first_table = discovered_tables[0]
    csv_path = first_table.get("csv_path", "")
    table_name = first_table.get("Ten_Bang", Path(csv_path).stem if csv_path else "unknown")
    metadata_set = set(METADATA_HEADER_COLUMNS)

    try:
        df_full = pd.read_csv(csv_path)
        raw_columns = list(df_full.columns)
        print(f"   📋 Đọc bảng '{table_name}' từ: {csv_path}")

        # ── 1, 2, 3, 4. Trích xuất useful_columns qua kiểm tra dữ liệu từng cột ──
        useful_columns = _extract_useful_columns(df_full, metadata_cols=metadata_set)

        # ── 5. Xác định động label_column và value_column (Không dùng danh sách ưu tiên) ──
        label_col = _find_label_column(useful_columns, raw_columns)
        value_col = _find_value_column(useful_columns, label_col, tieu_chi_phu, raw_columns)

        column_mapping = {
            "label_column": label_col,
            "value_column": value_col,
            "all_columns": str(raw_columns),
            "all_useful_columns": [c["raw_column"] for c in useful_columns],
        }

        print(f"\n   🎯 [Workflow Step 6: Xác định Cột Nhãn & Cột Giá Trị]")
        print(f"      • Cột nhãn (label_column): '{label_col}'")
        print(f"      • Cột giá trị (value_column): '{value_col}'")

        # ── 6. Phân tích Sub-sections ──
        sub_sections = _extract_sub_sections(df_full, label_col, metadata_set)
        if sub_sections:
            print(f"   📂 Phát hiện {len(sub_sections)} danh mục con (Sub-sections).")

        # ── 7. Sinh mô tả ngữ nghĩa cho các cột bằng LLM ──
        useful_columns = _enrich_column_descriptions(cfg, useful_columns, table_name)

        schema = {
            "useful_columns": useful_columns,
            "sub_sections": sub_sections,
        }

        # ── 8. In Output JSON phục vụ kiểm thử ──
        output_json = {
            "column_mapping": column_mapping,
            "schema": schema,
        }

        print(f"\n" + "-" * 65)
        print(f"📄 [SCHEMA MAPPER OUTPUT JSON - DÙNG CHO KIỂM THỬ]:")
        print(json.dumps(output_json, indent=2, ensure_ascii=False))
        print("-" * 65)

    except Exception as e:
        print(f"   ⚠️ [Schema Mapper] Lỗi trong quá trình phân tích schema: {e}")
        import traceback
        traceback.print_exc()

    latency = time.time() - start_time
    node_latencies = state.get("node_latencies", {})
    node_latencies["schema_mapper"] = round(latency, 3)

    print(f"\n   ⏱️ [Schema Mapper] Hoàn thành trong {latency:.3f}s")
    print(f"=" * 65 + "\n")

    return {
        **state,
        "column_mapping": column_mapping,
        "schema": schema,
        "status": "pending",
        "node_latencies": node_latencies,
    }

