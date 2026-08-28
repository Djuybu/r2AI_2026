"""Node 4: Code Generation & Reflection Node.
Sinh code Python/Pandas dựa trên mục tiêu (trich_xuat/tinh_tong/so_sanh),
cột mapping, và bảng dữ liệu đã tìm được.
Tất cả các prompt, quy tắc và template được nạp từ file prompts/code_generator.yaml & prompts/reflection.yaml.
"""

import re
import time
import yaml
from typing import Dict, Any, Optional, List
from langchain_core.messages import SystemMessage, HumanMessage

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.llm_provider import get_llm


def load_yaml_prompt(cfg: Config, filename: str) -> Dict[str, Any]:
    """Load prompt template YAML."""
    prompt_path = cfg.get_prompt_path(filename)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at: {prompt_path}")

    with open(prompt_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clean_python_code(raw_code: str) -> str:
    """Extract clean Python code from LLM response, stripping markdown and conversational text."""
    if not raw_code:
        return ""

    # Step 1: Check markdown python blocks
    pattern = r"```(?:python)?\s*\n?(.*?)\n?```"
    matches = re.findall(pattern, raw_code, re.DOTALL)
    if matches:
        return matches[0].strip()

    cleaned = raw_code.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()

    # Step 2: Strip conversational text before code
    lines = cleaned.splitlines()
    code_start_idx = 0
    for idx, line in enumerate(lines):
        l = line.strip()
        if l.startswith("import ") or l.startswith("def ") or l.startswith("file_path") or l.startswith("df =") or l.startswith("result ="):
            code_start_idx = idx
            break

    return "\n".join(lines[code_start_idx:]).strip()


# Các cột metadata/thông tin chung ở đầu file CSV
_METADATA_COLUMNS = {
    "Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "Nam_Tai_Chinh",
    "Loai_Bao_Cao", "Ten_Bang", "Don_Vi_Tinh", "Tep_Nguon"
}


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
    """Chọn cột giá trị dựa trên schema thực tế và dữ liệu hàng đầu tiên.

    Logic:
    1. Nếu schema rỗng hoặc không có thông tin: fallback column_mapping.
    2. Lọc ra các cột dữ liệu (loại bỏ metadata và label_column).
    3. Nếu chỉ có 1 cột dữ liệu (sau khi trừ label) → lấy cột đó.
    4. Nếu có >1 cột VÀ có schema useful_columns:
       so sánh tieu_chi_phu/noi_dung với column_name + column_description.
    5. Nếu có >1 cột VÀ các cột có tên là số (0,1,2,3...):
       dùng first_row_values để đoán cột đúng dựa vào tieu_chi_phu hoặc noi_dung/fallback.
    6. Fallback: dùng column_mapping["value_column"] như cũ.
    """
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

    # Trường hợp 1: Chỉ có 1 cột dữ liệu (sau khi đã trừ label) → lấy cột đó
    if len(data_cols) == 1:
        return data_cols[0]

    # Trường hợp 2: Có >1 cột VÀ có schema useful_columns → so sánh với mô tả
    useful_columns = schema.get("useful_columns", [])
    if len(useful_columns) > 1:
        tieu_chi_phu = parsed_query.get("tieu_chi_phu", "")
        noi_dung = parsed_query.get("noi_dung", "")
        search_terms = [t for t in [tieu_chi_phu, noi_dung] if t]

        for search_term in search_terms:
            search_lower = str(search_term).strip().lower()
            for uc in useful_columns:
                col_name = uc.get("column_name", "")
                col_desc = uc.get("column_description", "")
                # So sánh search_term với tên và mô tả cột
                if (search_lower in col_name.lower() or
                    search_lower in col_desc.lower() or
                    col_name.lower() in search_lower or
                    col_desc.lower() in search_lower):
                    # Tìm cột thực tế trong data_cols tương ứng
                    if col_name in data_cols:
                        print(f"   🎯 [Schema] Chọn cột '{col_name}' (mô tả: '{col_desc}') dựa trên '{search_term}'")
                        return col_name
                    # Cột có thể đã được rename từ số → tìm cột gốc
                    for dc in data_cols:
                        if str(dc).strip().isdigit():
                            # Cột gốc là số, useful_columns đã đổi tên
                            print(f"   🎯 [Schema] Chọn cột '{dc}' (→ '{col_name}', mô tả: '{col_desc}') dựa trên '{search_term}'")
                            return dc

    # Kiểm tra xem có cột tên là số không
    numeric_named_cols = [c for c in data_cols if str(c).strip().isdigit()]

    # Trường hợp 3: Có >1 cột và cột có tên là số → dùng first_row_values để đoán
    if numeric_named_cols and first_row_values:
        tieu_chi_phu = parsed_query.get("tieu_chi_phu", "")

        if tieu_chi_phu:
            # Tìm cột mà giá trị hàng đầu tiên khớp với tiêu chí phụ
            tieu_chi_lower = str(tieu_chi_phu).strip().lower()
            for col in data_cols:
                val = first_row_values.get(str(col), "")
                if tieu_chi_lower in val.lower():
                    print(f"   🎯 Chọn cột '{col}' (giá trị hàng đầu: '{val}') dựa trên tiêu chí phụ '{tieu_chi_phu}'")
                    return col

        # Nếu không tìm được theo tiêu chí phụ, dùng column_mapping fallback
        # nhưng ưu tiên tìm trong first_row_values xem cột nào có giá trị giống fallback
        for col in data_cols:
            val = first_row_values.get(str(col), "")
            if fallback.lower() in val.lower():
                print(f"   🎯 Chọn cột '{col}' (giá trị hàng đầu: '{val}') khớp với '{fallback}'")
                return col

    # Trường hợp 4: Không có cột tên số, hoặc không đoán được → dùng fallback nếu có trong data_cols, hoặc cột đầu tiên
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


def code_generator_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 4: Sinh code Pandas hoặc sửa code lỗi (Reflection Loop).

    Nạp prompt và hướng dẫn từ YAML, hỗ trợ các mục tiêu (trich_xuat, tinh_tong, so_sanh).

    Args:
        state: Current AgentState
        cfg: Config instance

    Returns:
        Updated AgentState with 'generated_code'
    """
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
            print(f"⚠️ Inline schema mapping failed: {e}")
    error_traceback = state.get("error_traceback")
    retry_count = state.get("retry_count", 0)

    # Extract parsed query fields
    muc_tieu = parsed_query.get("muc_tieu", "trich_xuat")
    noi_dung = parsed_query.get("noi_dung", "")
    ten_cong_ty = parsed_query.get("ten_cong_ty", "")
    so_nam = parsed_query.get("so_nam", [])
    tieu_chi_phu = parsed_query.get("tieu_chi_phu")

    # Detect person name if query involves remuneration / salary / executive personnel (Q15)
    person_name = parsed_query.get("ten_nhan_su") or parsed_query.get("person_name")
    if not person_name and isinstance(user_query, str):
        p_match = re.search(r"(?:thù lao|tiền lương|cổ phần|lương)\s+(?:của\s+)?([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})", user_query, re.IGNORECASE)
        if p_match:
            person_name = p_match.group(1).strip()

    # Get column names from mapping, sử dụng schema thực tế nếu có
    label_col = _resolve_label_column(table_schema, first_row_values, column_mapping, schema=schema)
    value_col = _resolve_value_column(table_schema, first_row_values, parsed_query, column_mapping, label_col, schema=schema)

    print(f"   📋 [Code Generator] Schema: {table_schema}")
    print(f"   📋 [Code Generator] Label col: '{label_col}', Value col: '{value_col}'")
    if person_name:
        print(f"   👤 [Code Generator] Nhận diện nhân sự/lãnh đạo: '{person_name}'")
    if first_row_values:
        print(f"   📋 [Code Generator] First row values: {first_row_values}")

    # Build files context (bao gồm schema và first_row info)
    files_context = _build_files_context(discovered_tables, column_mapping, table_schema, first_row_values, schema=schema)
    if person_name:
        files_context += f"\n\n👤 THỰC THỂ NHÂN SỰ/LÃNH ĐẠO: '{person_name}'. ƯU TIÊN LỌC THEO TÊN NÀY TRÊN CỘT NHÃN '{label_col}'."

    core_tokens = [t for t in re.findall(r"\w+", noi_dung) if len(t) > 2 and t.lower() not in ["tổng", "tổng_số", "số_dư", "chi_phí", "giá_trị", "chỉ_tiêu", "năm", "báo", "cáo"]]
    if core_tokens:
        files_context += f"\n🔑 TỪ KHÓA CỐT LÕI (DÙNG CHO MULTI-STAGE QUERY NẾU CẤP 1 RỖNG): {core_tokens}"

    # Build file path variables for code
    paths_str = ""
    if discovered_tables:
        top_csv = discovered_tables[0]["csv_path"].replace('\\', '\\\\')
        paths_str = f"file_path = '{top_csv}'\n"

        year_paths = {}
        for tbl in discovered_tables:
            nam = str(tbl.get("Nam_Tai_Chinh", "")).strip()
            csv_p = tbl.get("csv_path", "").replace('\\', '\\\\')
            if nam and nam not in year_paths:
                year_paths[nam] = csv_p
        if len(year_paths) > 1:
            for nam, csv_p in year_paths.items():
                paths_str += f"file_path_{nam} = '{csv_p}'\n"
    paths_str = paths_str.strip()

    try:
        # Scenario A: Initial Code Generation
        if not error_traceback or retry_count == 0:
            prompt_data = load_yaml_prompt(cfg, "code_generator.yaml")
            system_prompt = prompt_data["system_prompt"]
            few_shots = prompt_data.get("few_shot_examples", [])
            goal_descs = prompt_data.get("goal_descriptions", {})
            goal_instructions = prompt_data.get("goal_instructions", {})

            messages = [SystemMessage(content=system_prompt)]
            for ex in few_shots:
                messages.append(
                    HumanMessage(
                        content=f"Yêu cầu: {ex['user_query']}\n"
                                f"File Path: {ex['file_path']}\n"
                                f"Column Mapping: {ex['column_mapping']}"
                    )
                )
                messages.append(SystemMessage(content=ex["generated_code"]))

            # Retrieve goal description and goal instruction from YAML
            goal_desc = goal_descs.get(muc_tieu, muc_tieu)
            goal_inst_template = goal_instructions.get(muc_tieu, "")
            goal_inst = goal_inst_template.format(
                noi_dung=noi_dung, label_col=label_col, value_col=value_col
            ) if goal_inst_template else ""

            # Format user prompt from YAML template
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
                goal_instruction=goal_inst,
            )

            messages.append(HumanMessage(content=human_content))

        # Scenario B: Reflection Debugging Loop (retry_count > 0)
        else:
            prompt_data = load_yaml_prompt(cfg, "reflection.yaml")
            system_prompt = prompt_data["system_prompt"]

            if len(discovered_tables) > 1:
                # Multi-table fallback: rotate candidate tables on retry
                shift = retry_count % len(discovered_tables)
                discovered_tables = discovered_tables[shift:] + discovered_tables[:shift]
                first_table_path = discovered_tables[0]["csv_path"]
                schema_info = _extract_table_schema(first_table_path)
                table_schema = schema_info["table_schema"]
                first_row_values = schema_info["first_row_values"]
                state["discovered_tables"] = discovered_tables
                state["matched_table_path"] = first_table_path
                state["table_schema"] = table_schema
                state["first_row_values"] = first_row_values
                from pipeline.src.nodes.schema_mapper import schema_mapper_node
                try:
                    temp_state = schema_mapper_node(state, cfg)
                    column_mapping = temp_state.get("column_mapping", {})
                    schema = temp_state.get("schema", {})
                    state["column_mapping"] = column_mapping
                    state["schema"] = schema
                    label_col = _resolve_label_column(table_schema, first_row_values, column_mapping, schema=schema)
                    value_col = _resolve_value_column(table_schema, first_row_values, parsed_query, column_mapping, label_col, schema=schema)
                    files_context = _build_files_context(discovered_tables, column_mapping, table_schema, first_row_values, schema=schema)
                except Exception as e:
                    print(f"⚠️ Multi-table fallback schema mapping failed: {e}")

            print(f"🔄 [Reflection Loop] Đang sửa lỗi mã nguồn (Lần {retry_count})...")
            print(f"   - Bảng được chọn: {discovered_tables[0].get('Ten_Bang')} ({discovered_tables[0].get('csv_path')})")
            print(f"   - Traceback Lỗi:\n{error_traceback.strip()}")

            retry_forcing_msg = (
                f"Execution failed with error: {error_traceback.strip()}\n"
                "CRITICAL: The string you used in `str.contains()` was NOT found in the table. "
                "DO NOT output the exact same code again! "
                "You MUST change your search strategy: shorten the search string in `str.contains(..., regex=False)` to a single core keyword from the metric, or inspect the sample row labels below."
            )

            sample_labels = []
            if discovered_tables:
                from pathlib import Path
                import pandas as pd
                for tbl in discovered_tables:
                    c_path = tbl.get("csv_path")
                    if c_path and Path(c_path).exists():
                        try:
                            sub_df = pd.read_csv(c_path)
                            if label_col in sub_df.columns:
                                labels = sub_df[label_col].dropna().astype(str).head(20).tolist()
                                sample_labels.append(f"Mẫu chỉ tiêu thực tế trong file '{Path(c_path).name}':\n{labels}")
                        except Exception:
                            pass
            sample_labels_str = "\n\n".join(sample_labels) if sample_labels else ""

            user_template = prompt_data.get("user_prompt_template", "")
            human_content = user_template.format(
                user_query=user_query,
                muc_tieu=muc_tieu,
                noi_dung=noi_dung,
                files_context=files_context,
                label_col=label_col,
                value_col=value_col,
                paths_str=paths_str,
                sample_labels_str=sample_labels_str,
                previous_code=state.get('generated_code', ''),
                error_traceback=f"{error_traceback.strip()}\n\n{retry_forcing_msg}",
            )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_content)
            ]

        # Call LLM
        llm = get_llm(cfg=cfg, temperature=0.0)
        response = llm.invoke(messages)
        raw_text = response.content if isinstance(response.content, str) else str(response.content)

        # Extract and print thoughts
        think_match = re.search(r"<think>(.*?)</think>", raw_text, re.DOTALL)
        if think_match:
            thought = think_match.group(1).strip()
            indented_thought = thought.replace('\n', '\n  ')
            print(f"💭 [Tư duy - Code Generator]:\n  {indented_thought}")
        else:
            code_start = raw_text.find("```")
            if code_start > 10:
                thought = raw_text[:code_start].strip()
                indented_thought = thought.replace('\n', '\n  ')
                print(f"💭 [Tư duy - Code Generator]:\n  {indented_thought}")

        code = clean_python_code(raw_text)

        print(f"📊 [Kết quả - Code Generator] Mã Python sinh ra:\n```python\n{code}\n```\n")

        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["code_generator"] = round(latency, 3)

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

        return {
            **state,
            "status": "error",
            "error_message": f"Code generator node error: {str(e)}",
            "node_latencies": node_latencies,
        }