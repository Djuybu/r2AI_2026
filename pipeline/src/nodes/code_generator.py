"""Node 4: Code Generation & Reflection Node.
Sinh code Python/Pandas dựa trên mục tiêu (trich_xuat/tinh_tong/so_sanh),
cột mapping, và bảng dữ liệu đã tìm được.
Tất cả các prompt, quy tắc và template được nạp từ file prompts/code_generator.yaml & prompts/reflection.yaml.
"""

import re
import time
import yaml
import pandas as pd
from pathlib import Path
from typing import Dict, Any, Optional, List
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.llm_provider import get_llm
from pipeline.src.nodes.data_discovery import _extract_table_schema


def load_yaml_prompt(cfg: Config, filename: str) -> Dict[str, Any]:
    """Load prompt template YAML with fallback to Kaggle global prompt dicts."""
    try:
        if hasattr(cfg, "get_prompt_path"):
            prompt_path = cfg.get_prompt_path(filename)
            if prompt_path and Path(prompt_path).exists():
                with open(prompt_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
    except Exception:
        pass

    if "code_generator" in filename and "PROMPT_CODE_GENERATOR" in globals():
        return globals()["PROMPT_CODE_GENERATOR"]
    elif "reflection" in filename and "PROMPT_REFLECTION" in globals():
        return globals()["PROMPT_REFLECTION"]

    raise FileNotFoundError(f"Prompt file {filename} not found and no global fallback available.")


def clean_python_code(raw_code: str) -> str:
    """Extract clean Python code from LLM response, stripping markdown and trailing conversational text."""
    if not raw_code:
        return ""

    import ast
    import re

    # Remove thinking tags first
    cleaned_raw = re.sub(r"<think>.*?</think>", "", raw_code, flags=re.DOTALL).strip()

    def try_parse_and_trim(code_text: str) -> str:
        code_text = code_text.strip()
        if not code_text:
            return ""
        # 1. Try parsing directly
        try:
            ast.parse(code_text)
            return code_text
        except SyntaxError:
            pass

        # 2. Try trimming trailing non-python text line-by-line from bottom
        lines = code_text.splitlines()
        for i in range(len(lines) - 1, 0, -1):
            sub_code = "\n".join(lines[:i]).strip()
            if not sub_code:
                break
            try:
                ast.parse(sub_code)
                return sub_code
            except SyntaxError:
                pass
        return ""

    # Step 1: Check markdown python blocks
    pattern = r"```(?:python)?\s*\n?(.*?)\n?```"
    matches = re.findall(pattern, cleaned_raw, re.DOTALL)
    for match in matches:
        res = try_parse_and_trim(match)
        if res:
            return res

    # Step 2: Strip code fences if present at boundary
    if cleaned_raw.startswith("```") and cleaned_raw.endswith("```"):
        boundary_stripped = cleaned_raw.strip("`").strip()
        if boundary_stripped.startswith("python"):
            boundary_stripped = boundary_stripped[6:].strip()
        res = try_parse_and_trim(boundary_stripped)
        if res:
            return res

    # Step 3: Strip conversational text before and after code
    lines = cleaned_raw.splitlines()
    for idx, line in enumerate(lines):
        l = line.strip()
        if l.startswith("import ") or l.startswith("def ") or l.startswith("file_path") or l.startswith("df =") or l.startswith("result ="):
            candidate = "\n".join(lines[idx:]).strip()
            res = try_parse_and_trim(candidate)
            if res:
                return res

    return ""



_METADATA_COLUMNS = {
    "Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "Nam_Tai_Chinh",
    "Loai_Bao_Cao", "Ten_Bang", "Don_Vi_Tinh", "Tep_Nguon"
}

_PERSON_BLOCKLIST = {
    "và các khoản khác", "các khoản khác", "đã phát hành", "đã phát hành của",
    "quản lý doanh nghiệp", "phát hành thêm", "công ty mẹ", "chi phí",
    "doanh thu", "lợi nhuận", "vốn chủ sở hữu", "vốn cổ phần", "tổng giám đốc",
    "hội đồng quản trị", "chứng khoán fpt", "báo cáo tài chính", "tổng công ty",
    "hàng không vietjet", "ngân hàng tmcp", "tập đoàn", "công ty cổ phần"
}


def extract_person_name(user_query: str) -> Optional[str]:
    """Extract executive person name from financial query, rejecting financial line item false positives."""
    if not user_query:
        return None
    q_lower = user_query.lower()
    if any(k in q_lower for k in [
        "chi phí lương", "quỹ lương", "vốn cổ phần", "cổ phần đã phát hành",
        "tỷ lệ sở hữu", "quyền biểu quyết", "tỷ lệ biểu quyết", "chi phí quản lý"
    ]):
        return None

    # Priority 1: Match title prefix + Capitalized Name
    m = re.search(
        r"(?i:(?:thành viên\s+(?:hđqt|hội đồng quản trị|bqt|bks|ban kiểm soát|ban tổng giám đốc|ban giám đốc)|chủ tịch(?:\s+hđqt)?|tổng giám đốc|tgđ|phó tổng giám đốc|phó tgđ|ông|bà))\s+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})",
        user_query
    )
    if m:
        cand = m.group(1).strip()
        if cand.lower() not in _PERSON_BLOCKLIST:
            return cand

    # Priority 2: Remuneration / Salary of person
    m2 = re.search(
        r"(?i:(?:thù lao|tiền lương|thưởng|thu nhập)\s+(?:của\s+)?(?:ông\s+|bà\s+)?)([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})",
        user_query
    )
    if m2:
        cand = m2.group(1).strip()
        if cand.lower() not in _PERSON_BLOCKLIST and not any(cand.lower().startswith(b) for b in ["ctcp", "ngân hàng", "công ty", "tập đoàn", "chứng khoán"]):
            return cand
    return None


def generate_fallback_code(
    muc_tieu: str,
    noi_dung: str,
    label_col: str,
    value_col: str,
    so_nam: List[str],
    discovered_tables: List[Dict[str, Any]],
    person_name: Optional[str] = None,
    tieu_chi_phu: Optional[str] = None,
    user_query: str = "",
    label_col_idx: Optional[int] = None,
    value_col_idx: Optional[int] = None,
) -> str:
    """Generate concise Pandas extraction code using column position indices from Schema Mapper."""
    escaped_noi_dung = (noi_dung or "").replace("'", "\\'").strip()
    escaped_person = (person_name or "").replace("'", "\\'").strip()
    escaped_tieu_chi = (tieu_chi_phu or "").replace("'", "\\'").strip()

    is_growth = any(k in user_query.lower() for k in ["tăng trưởng", "tốc độ", "%", "thay đổi"])

    lbl_ref = f"df.iloc[:, {label_col_idx}]" if label_col_idx is not None else f"df['{label_col}']"
    val_arg = value_col_idx if value_col_idx is not None else f"'{value_col}'"

    code_lines = [
        "import pandas as pd",
        "import numpy as np",
        "df = pd.read_csv(file_path)",
        f"# Truy vấn trực tiếp theo vị trí cột: label_col='{label_col}', value_col='{value_col}'",
    ]

    if person_name:
        code_lines.extend([
            f"# Lọc trực tiếp theo thực thể nhân sự: '{escaped_person}'",
            f"filtered_df = df[{lbl_ref}.astype(str).str.contains('{escaped_person}', case=False, na=False, regex=False)]",
            "if not filtered_df.empty:",
            "    match_row = filtered_df.iloc[0]",
            f"    result = extract_value(match_row, {val_arg}, _df=df, _row_idx=match_row.name)",
            "else:",
            f"    raise ValueError(\"Person '{escaped_person}' not found in table\")",
        ])
        return "\n".join(code_lines)

    if muc_tieu == "so_sanh" and len(so_nam) >= 2:
        y_sorted = sorted(so_nam, key=lambda y: int(y) if str(y).isdigit() else 0)
        y_old, y_new = y_sorted[0], y_sorted[-1]

        code_lines.extend([
            f"# So sánh giữa các năm {so_nam}",
            f"search_key = '{escaped_noi_dung}'",
            f"filtered_df = df[{lbl_ref}.astype(str).str.contains(search_key, case=False, na=False, regex=False)]",
            "if filtered_df.empty:",
            f"    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và', 'các', 'khoản', 'theo']]",
            "    for t in tokens:",
            f"        filtered_df = df[{lbl_ref}.astype(str).str.contains(t, case=False, na=False, regex=False)]",
            "        if not filtered_df.empty:",
            "            break",
            "if not filtered_df.empty:",
            "    match_row = filtered_df.iloc[0]",
            "    _meta = {'Ma_Doanh_Nghiep', 'Ten_Doanh_Nghiep', 'Nam_Tai_Chinh', 'Loai_Bao_Cao', 'Ten_Bang', 'Don_Vi_Tinh', 'Tep_Nguon'}",
            "    cols = [c for c in df.columns if c not in _meta]",
            f"    col_new = next((c for c in cols if '{y_new}' in str(c)), {val_arg})",
            f"    col_old = next((c for c in cols if '{y_old}' in str(c)), cols[1] if len(cols) > 1 else col_new)",
            "    val_new = extract_value(match_row, col_new, _df=df, _row_idx=match_row.name)",
            "    val_old = extract_value(match_row, col_old, _df=df, _row_idx=match_row.name)",
        ])
        if is_growth:
            code_lines.append("    result = ((val_new - val_old) / abs(val_old)) * 100 if val_old != 0 else 0.0")
        else:
            code_lines.append("    result = val_new - val_old")
        code_lines.extend([
            "else:",
            f"    raise ValueError(\"Metric '{escaped_noi_dung}' not found in table\")",
        ])
        return "\n".join(code_lines)

    # Standard direct extraction
    code_lines.extend([
        f"search_key = '{escaped_noi_dung}'",
        f"filtered_df = df[{lbl_ref}.astype(str).str.contains(search_key, case=False, na=False, regex=False)]",
        "if filtered_df.empty:",
        "    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và', 'các', 'khoản', 'theo', 'công', 'mẹ', 'đã', 'phát', 'hành']]",
        "    for t in tokens:",
        f"        filtered_df = df[{lbl_ref}.astype(str).str.contains(t, case=False, na=False, regex=False)]",
        "        if not filtered_df.empty:",
        "            break",
        "if not filtered_df.empty:",
        "    match_row = filtered_df.iloc[0]",
        f"    result = extract_value(match_row, {val_arg}, _df=df, _row_idx=match_row.name)",
        "else:",
        f"    raise ValueError(\"Metric '{escaped_noi_dung}' not found in table\")",
    ])
    return "\n".join(code_lines)


def _resolve_label_column(
    table_schema: List[str],
    first_row_values: Optional[Dict[str, str]] = None,
    column_mapping: Optional[Dict[str, str]] = None,
    schema: Optional[Dict[str, Any]] = None,
) -> str:
    """Chọn cột nhãn (chứa tên chỉ tiêu tài chính) dựa trên column_mapping và schema thực tế.

    Logic:
    1. Nếu column_mapping có label_column và cột đó thực sự tồn tại trong table_schema -> dùng nó.
    2. Nếu có schema useful_columns -> lấy cột dạng text đầu tiên.
    3. Lấy cột đầu tiên trong table_schema không thuộc _METADATA_COLUMNS.
    4. Fallback: column_mapping['label_column'] nếu có, hoặc cột đầu tiên.
    """
    column_mapping = column_mapping or {}
    schema = schema or {}

    # 1. Kiểm tra column_mapping nếu cột đó thực sự có trong table_schema
    mapped_label = column_mapping.get("label_column")
    if mapped_label and mapped_label in table_schema:
        return mapped_label

    # 2. Kiểm tra useful_columns trong schema
    useful_cols = schema.get("useful_columns", [])
    text_cols = [c.get("raw_column") for c in useful_cols if c.get("data_type") == "text"]
    for tc in text_cols:
        if tc in table_schema:
            return tc

    if not table_schema:
        return mapped_label or "0"

    # 3. Lấy cột đầu tiên không phải metadata
    non_meta_cols = [c for c in table_schema if c not in _METADATA_COLUMNS]
    if non_meta_cols:
        return non_meta_cols[0]

    return mapped_label or table_schema[0]


def _resolve_value_column(
    table_schema: List[str],
    first_row_values: Dict[str, str],
    parsed_query: Dict[str, Any],
    column_mapping: Dict[str, str],
    label_col: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
) -> str:
    """Chọn cột giá trị dựa trên schema thực tế, tiêu chí phụ và dữ liệu hàng đầu tiên."""
    fallback = column_mapping.get("value_column", "Năm nay")
    schema = schema or {}

    if not table_schema:
        return fallback

    label_col = label_col or column_mapping.get("label_column", "")

    # Lọc cột dữ liệu (loại bỏ metadata + label)
    data_cols = [
        c for c in table_schema
        if c not in _METADATA_COLUMNS and c != label_col
    ]

    if not data_cols:
        return fallback

    if len(data_cols) == 1:
        return data_cols[0]

    tieu_chi_phu = parsed_query.get("tieu_chi_phu", "")
    noi_dung = parsed_query.get("noi_dung", "")

    # 1. So sánh tiêu chí phụ trực tiếp với tên các cột dữ liệu
    if tieu_chi_phu:
        tcp_lower = str(tieu_chi_phu).strip().lower()
        for col in data_cols:
            col_str = str(col).strip().lower()
            if tcp_lower in col_str or col_str in tcp_lower:
                print(f"   🎯 [Code Generator] Tự chọn cột '{col}' khớp với tiêu chí phụ '{tieu_chi_phu}'")
                return col

        m_year = re.search(r"\b(19|20)\d{2}\b", tcp_lower)
        if m_year:
            target_year = m_year.group(0)
            for col in data_cols:
                if target_year in str(col):
                    print(f"   🎯 [Code Generator] Tự chọn cột '{col}' khớp với năm '{target_year}' từ tiêu chí phụ")
                    return col

        if any(kw in tcp_lower for kw in ["%", "phần trăm", "tỷ lệ", "biểu quyết", "sở hữu"]):
            for col in data_cols:
                if any(k in str(col).lower() for k in ["%", "tỷ lệ", "biểu quyết", "sở hữu"]):
                    print(f"   🎯 [Code Generator] Tự chọn cột '{col}' khớp với chỉ tiêu tỷ lệ % từ tiêu chí phụ")
                    return col

    # 2. So sánh với useful_columns từ schema
    useful_columns = schema.get("useful_columns", [])
    if useful_columns:
        for uc in useful_columns:
            c_name = str(uc.get("column_name", ""))
            r_name = str(uc.get("raw_column", ""))
            if tieu_chi_phu and (str(tieu_chi_phu).lower() in c_name.lower() or str(tieu_chi_phu).lower() in r_name.lower()):
                target_col = r_name if r_name in data_cols else c_name
                if target_col in data_cols:
                    print(f"   🎯 [Code Generator] Tự chọn cột '{target_col}' từ useful_columns dựa trên '{tieu_chi_phu}'")
                    return target_col

    # 3. Nếu cột có tên là số (0, 1, 2...), dùng first_row_values để đoán cột đúng
    numeric_named_cols = [c for c in data_cols if str(c).strip().isdigit()]
    if numeric_named_cols and first_row_values and tieu_chi_phu:
        tcp_lower = str(tieu_chi_phu).strip().lower()
        for col in data_cols:
            val = str(first_row_values.get(str(col), "")).lower()
            if tcp_lower in val:
                print(f"   🎯 [Code Generator] Tự chọn cột '{col}' (hàng 1: '{val}') từ tiêu chí phụ '{tieu_chi_phu}'")
                return col

    if fallback in data_cols:
        return fallback

    return data_cols[0] if data_cols else fallback


def _build_files_context(
    discovered_tables: List[Dict[str, Any]],
    column_mapping: Dict[str, str],
    table_schema: List[str] = None,
    first_row_values: Dict[str, str] = None,
    schema: Dict[str, Any] = None,
) -> str:
    """Build context string describing available files for code generation."""
    if not discovered_tables:
        return "Không có bảng dữ liệu."

    lines = []
    for i, tbl in enumerate(discovered_tables):
        csv_path = tbl.get("csv_path", "")
        ten_bang = tbl.get("Ten_Bang", "N/A")
        nam = tbl.get("Nam_Tai_Chinh", "N/A")
        escaped_path = csv_path.replace('\\', '\\\\')
        lines.append(
            f"- File {i+1} (Năm {nam}):\n"
            f"  Đường dẫn: '{escaped_path}'\n"
            f"  Tên bảng: {ten_bang}\n"
        )

    lines.append(f"\nColumn Mapping: {column_mapping}")

    # Thêm thông tin schema bảng
    if table_schema:
        lines.append(f"\nSchema bảng (tên các cột): {table_schema}")

    # Thêm giá trị hàng đầu tiên nếu có cột tên là số
    if first_row_values:
        lines.append(f"\nGiá trị hàng đầu tiên (giúp hiểu ý nghĩa cột số):")
        for col, val in first_row_values.items():
            lines.append(f"  Cột '{col}' → '{val}'")

    # Thêm schema analysis context (useful_columns + sub_sections)
    schema = schema or {}
    useful_columns = schema.get("useful_columns", [])
    sub_sections = schema.get("sub_sections", [])

    if useful_columns:
        lines.append(f"\nSCHEMA PHÂN TÍCH BẢNG - CỘT GIÁ TRỊ HỮU DỤNG:")
        for uc in useful_columns:
            col_name = uc.get("column_name", "")
            col_desc = uc.get("column_description", "")
            desc_str = f" — {col_desc}" if col_desc else ""
            lines.append(f"  • '{col_name}'{desc_str}")

    if sub_sections:
        lines.append(f"\nSCHEMA PHÂN TÍCH BẢNG - DANH MỤC CON (SUB-SECTIONS):")
        for sec in sub_sections:
            sec_name = sec.get("section_name", "")
            sec_range = sec.get("range", [])
            total_val = sec.get("total_value")
            total_str = f", total_value={total_val}" if total_val is not None else ", total_value=N/A"
            lines.append(f"  • '{sec_name}' (hàng {sec_range[0]}–{sec_range[1]}{total_str})")

    # Add sample row labels from the label column so LLM sees actual text entries
    label_col = column_mapping.get("label_column")
    if discovered_tables and label_col:
        from pathlib import Path
        c_path = discovered_tables[0].get("csv_path")
        if c_path and Path(c_path).exists():
            try:
                sub_df = pd.read_csv(c_path)
                if label_col in sub_df.columns:
                    sample_labels = sub_df[label_col].dropna().astype(str).head(15).tolist()
                    if sample_labels:
                        lines.append(f"\nMẪU NHÃN HÀNG THỰC TẾ TRONG CỘT '{label_col}':")
                        for lbl in sample_labels:
                            lines.append(f"  • '{lbl}'")
            except Exception:
                pass

    return "\n".join(lines)


def ensure_code_variables(code: str, file_path: str, label_col: str, value_col: str, label_col_idx: Optional[int], value_col_idx: Optional[int]) -> str:
    """Prepend variable definitions to LLM generated code if referenced but undefined."""
    if not code:
        return ""

    import ast
    header_lines = []
    if "file_path" in code and not ("file_path =" in code or "file_path=" in code):
        header_lines.append(f"file_path = '{file_path}'")
    if "label_col" in code and not ("label_col =" in code or "label_col=" in code):
        header_lines.append(f"label_col = '{label_col}'")
    if "value_col" in code and not ("value_col =" in code or "value_col=" in code):
        header_lines.append(f"value_col = '{value_col}'")
    if label_col_idx is not None and "label_col_idx" in code and not ("label_col_idx =" in code or "label_col_idx=" in code):
        header_lines.append(f"label_col_idx = {label_col_idx}")
    if value_col_idx is not None and "value_col_idx" in code and not ("value_col_idx =" in code or "value_col_idx=" in code):
        header_lines.append(f"value_col_idx = {value_col_idx}")

    if header_lines:
        code = "\n".join(header_lines) + "\n" + code

    try:
        ast.parse(code)
    except Exception:
        pass
    return code


def code_generator_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 4: Sinh code Pandas hoặc sửa code lỗi (Reflection Loop)."""
    cfg = cfg or default_config
    start_time = time.time()

    user_query = state.get("user_query", "")
    parsed_query = state.get("parsed_query", {})
    discovered_tables = state.get("discovered_tables", [])
    column_mapping = state.get("column_mapping", {})
    table_schema = state.get("table_schema", [])
    first_row_values = state.get("first_row_values", {})
    schema = state.get("schema", {})

    if (not column_mapping or not schema) and discovered_tables:
        from pipeline.src.nodes.schema_mapper import schema_mapper_node
        try:
            temp_state = schema_mapper_node(state, cfg)
            column_mapping = temp_state.get("column_mapping", {})
            schema = temp_state.get("schema", {})
            state["column_mapping"] = column_mapping
            state["schema"] = schema
        except Exception as e:
            pass

    error_traceback = state.get("error_traceback")
    retry_count = state.get("retry_count", 0)

    muc_tieu = parsed_query.get("muc_tieu", "trich_xuat")
    noi_dung = parsed_query.get("noi_dung", "")
    ten_cong_ty = parsed_query.get("ten_cong_ty", "")
    so_nam = parsed_query.get("so_nam", [])
    tieu_chi_phu = parsed_query.get("tieu_chi_phu")

    person_name = parsed_query.get("ten_nhan_su") or parsed_query.get("person_name")
    if not person_name and isinstance(user_query, str):
        person_name = extract_person_name(user_query)

    label_col = _resolve_label_column(table_schema, first_row_values, column_mapping, schema=schema)
    value_col = _resolve_value_column(table_schema, first_row_values, parsed_query, column_mapping, label_col, schema=schema)

    label_col_idx = column_mapping.get("label_column_idx")
    if label_col_idx is None and label_col in table_schema:
        label_col_idx = table_schema.index(label_col)

    value_col_idx = column_mapping.get("value_column_idx")
    if value_col_idx is None and value_col in table_schema:
        value_col_idx = table_schema.index(value_col)

    top_csv = discovered_tables[0]["csv_path"] if discovered_tables else "None"
    top_csv_basename = Path(top_csv).name

    print(f"\n🔍 [Node 4: Code Generator] Bắt đầu sinh mã Python...")
    print(f"   📋 Chỉ tiêu: '{noi_dung}' | Cột nhãn: '{label_col}' (idx={label_col_idx}) | Cột giá trị: '{value_col}' (idx={value_col_idx})")
    print(f"   📄 File nguồn: {top_csv_basename}")
    if person_name:
        print(f"   👤 Thực thể nhân sự: '{person_name}'")

    files_context = _build_files_context(discovered_tables, column_mapping, table_schema, first_row_values, schema=schema)
    if person_name:
        files_context += f"\n\n👤 THỰC THỂ NHÂN SỰ: '{person_name}'. ƯU TIÊN LỌC THEO TÊN NÀY TRÊN CỘT NHÃN '{label_col}'."

    core_tokens = [t for t in re.findall(r"\w+", noi_dung) if len(t) > 2 and t.lower() not in ["tổng", "tổng_số", "số_dư", "chi_phí", "giá_trị", "chỉ_tiêu", "năm", "báo", "cáo"]]
    if core_tokens:
        files_context += f"\n🔑 TỪ KHÓA CỐT LÕI: {core_tokens}"

    paths_str = ""
    if discovered_tables:
        top_csv_escaped = top_csv.replace('\\', '\\\\')
        paths_str = f"file_path = '{top_csv_escaped}'\n"

    try:
        if retry_count == 0:
            prompt_data = load_yaml_prompt(cfg, "code_generator.yaml")
            system_prompt = prompt_data.get("system_prompt", "")
            few_shots = prompt_data.get("few_shots", [])
            goal_descs = prompt_data.get("goal_descriptions", {})
            goal_instructions = prompt_data.get("goal_instructions", {})

            messages = [SystemMessage(content=system_prompt)]
            for ex in few_shots:
                messages.append(
                    HumanMessage(
                        content=f"Yêu cầu: {ex['user_query']}\nFile Path: {ex['file_path']}\nColumn Mapping: {ex['column_mapping']}"
                    )
                )
                messages.append(AIMessage(content=ex["generated_code"]))

            goal_desc = goal_descs.get(muc_tieu, muc_tieu)
            goal_inst_template = goal_instructions.get(muc_tieu, "")
            goal_inst = goal_inst_template.format(
                noi_dung=noi_dung, label_col=label_col, value_col=value_col
            ) if goal_inst_template else ""

            sample_labels = []
            if discovered_tables:
                for tbl in discovered_tables[:2]:
                    c_path = tbl.get("csv_path")
                    if c_path and Path(c_path).exists():
                        try:
                            sub_df = pd.read_csv(c_path)
                            if label_col in sub_df.columns:
                                labels = sub_df[label_col].dropna().astype(str).head(5).tolist()
                                sample_labels.append(f"Mẫu chỉ tiêu trong '{Path(c_path).name}': {labels}")
                        except Exception:
                            pass
            sample_labels_str = "\n".join(sample_labels) if sample_labels else ""

            user_template = prompt_data.get("user_prompt_template", "")
            human_content = user_template.format(
                user_query=user_query,
                muc_tieu_desc=goal_desc,
                noi_dung=noi_dung,
                ten_cong_ty=ten_cong_ty,
                so_nam=so_nam,
                tieu_chi_phu=tieu_chi_phu or "(không có)",
                files_context=files_context,
                label_col=label_col,
                value_col=value_col,
                paths_str=paths_str,
                sample_labels_str=sample_labels_str,
                goal_instruction=goal_inst,
            )
            messages.append(HumanMessage(content=human_content))

        else:
            prompt_data = load_yaml_prompt(cfg, "reflection.yaml")
            system_prompt = prompt_data.get("system_prompt", "")
            user_template = prompt_data.get("user_prompt_template", "")

            sample_labels_str = ""
            retry_forcing_msg = "SỬA LỖI: Rút ngắn từ khóa lọc str.contains() sang từ khóa ngắn nhất."
            human_content = user_template.format(
                user_query=user_query,
                muc_tieu=muc_tieu,
                noi_dung=noi_dung,
                files_context=files_context,
                label_col=label_col,
                value_col=value_col,
                paths_str=paths_str,
                sample_labels_str=sample_labels_str,
                previous_code=state.get("generated_code", ""),
                error_traceback=f"{str(error_traceback).strip()}\n\n{retry_forcing_msg}",
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_content)
            ]

        # Call LLM safely
        llm = get_llm(cfg=cfg, temperature=0.0)
        response = llm.invoke(messages)
        raw_text = response.content if isinstance(response.content, str) else str(response.content)

        think_match = re.search(r"<think>(.*?)</think>", raw_text, re.DOTALL)
        if think_match:
            thought = think_match.group(1).strip()
            indented_thought = thought.replace('\n', '\n  ')
            print(f"💭 [Tư duy - Code Generator]:\n  {indented_thought}")

        print(f"📄 [LLM Raw Response]:\n{raw_text.strip()}\n")

        code = clean_python_code(raw_text)

        if not code:
            print("⚠️ [Code Generator] LLM không sinh code hợp lệ -> Kích hoạt Rule-based Fallback Generator...")
            code = generate_fallback_code(
                muc_tieu=muc_tieu,
                noi_dung=noi_dung,
                label_col=label_col,
                value_col=value_col,
                so_nam=so_nam,
                discovered_tables=discovered_tables,
                person_name=person_name,
                tieu_chi_phu=tieu_chi_phu,
                user_query=user_query,
                label_col_idx=label_col_idx,
                value_col_idx=value_col_idx,
            )

        print(f"📊 [Mã Python Sinh Ra]:\n```python\n{code}\n```\n")

        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["code_generator"] = round(latency, 3)
        print(f"✅ [Node 4: Code Generator] Hoàn thành trong {node_latencies['code_generator']}s")

        return {
            **state,
            "generated_code": code,
            "status": "pending",
            "node_latencies": node_latencies,
        }

    except Exception as e:
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["code_generator"] = round(latency, 3)

        print(f"⚠️ [Code Generator] Lỗi gọi LLM ({e}) -> Kích hoạt Rule-based Fallback Generator...")
        fallback_code = generate_fallback_code(
            muc_tieu=muc_tieu,
            noi_dung=noi_dung,
            label_col=label_col,
            value_col=value_col,
            so_nam=so_nam,
            discovered_tables=discovered_tables,
            person_name=person_name,
            tieu_chi_phu=tieu_chi_phu,
            user_query=user_query,
            label_col_idx=label_col_idx,
            value_col_idx=value_col_idx,
        )

        print(f"📊 [Mã Python Fallback]:\n```python\n{fallback_code}\n```\n")
        print(f"✅ [Node 4: Code Generator] Hoàn thành trong {node_latencies['code_generator']}s")

        return {
            **state,
            "generated_code": fallback_code,
            "status": "pending",
            "node_latencies": node_latencies,
        }
