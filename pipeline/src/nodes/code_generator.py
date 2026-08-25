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


def _resolve_value_column(
    table_schema: List[str],
    first_row_values: Dict[str, str],
    parsed_query: Dict[str, Any],
    column_mapping: Dict[str, str],
) -> str:
    """Chọn cột giá trị dựa trên schema thực tế và dữ liệu hàng đầu tiên.

    Logic:
    1. Nếu schema rỗng hoặc không có thông tin: fallback column_mapping.
    2. Lọc ra các cột dữ liệu (loại bỏ metadata và label_column).
    3. Nếu chỉ có 2 cột dữ liệu → lấy cột thứ hai.
    4. Nếu có >2 cột VÀ các cột có tên là số (0,1,2,3...):
       dùng first_row_values để đoán cột đúng dựa vào tieu_chi_phu hoặc noi_dung.
    5. Fallback: dùng column_mapping["value_column"] như cũ.
    """
    fallback = column_mapping.get("value_column", "Năm nay")

    if not table_schema:
        return fallback

    label_col = column_mapping.get("label_column", "")

    # Lọc cột dữ liệu (loại bỏ metadata + label)
    data_cols = [
        c for c in table_schema
        if c not in _METADATA_COLUMNS and c != label_col
    ]

    if not data_cols:
        return fallback

    # Trường hợp 1: Chỉ có 2 cột dữ liệu (label + 1 value) → lấy cột thứ hai
    if len(data_cols) == 1:
        return data_cols[0]

    # Kiểm tra xem có cột tên là số không
    numeric_named_cols = [c for c in data_cols if str(c).strip().isdigit()]

    # Trường hợp 2: Có >2 cột và cột có tên là số → dùng first_row_values để đoán
    if len(data_cols) > 1 and numeric_named_cols and first_row_values:
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

    # Trường hợp 3: Không có cột tên số, hoặc không đoán được → dùng fallback
    return fallback


def _build_files_context(
    discovered_tables: List[Dict[str, Any]],
    column_mapping: Dict[str, str],
    table_schema: List[str] = None,
    first_row_values: Dict[str, str] = None,
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
    if not column_mapping and discovered_tables:
        from pipeline.src.nodes.schema_mapper import schema_mapper_node
        try:
            temp_state = schema_mapper_node(state, cfg)
            column_mapping = temp_state.get("column_mapping", {})
            state["column_mapping"] = column_mapping
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

    # Get column names from mapping, sử dụng schema thực tế nếu có
    label_col = column_mapping.get("label_column", "CHỈ TIÊU")
    value_col = _resolve_value_column(table_schema, first_row_values, parsed_query, column_mapping)

    print(f"   📋 [Code Generator] Schema: {table_schema}")
    print(f"   📋 [Code Generator] Label col: '{label_col}', Value col: '{value_col}'")
    if first_row_values:
        print(f"   📋 [Code Generator] First row values: {first_row_values}")

    # Build files context (bao gồm schema và first_row info)
    files_context = _build_files_context(discovered_tables, column_mapping, table_schema, first_row_values)

    # Build file path variables for code
    paths_str = ""
    if discovered_tables:
        if len(discovered_tables) == 1:
            escaped = discovered_tables[0]["csv_path"].replace('\\', '\\\\')
            paths_str = f"file_path = '{escaped}'"
        else:
            for tbl in discovered_tables:
                nam = tbl.get("Nam_Tai_Chinh", "default")
                escaped = tbl["csv_path"].replace('\\', '\\\\')
                paths_str += f"file_path_{nam} = '{escaped}'\n"

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

            print(f"🔄 [Reflection Loop] Đang sửa lỗi mã nguồn (Lần {retry_count})...")
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