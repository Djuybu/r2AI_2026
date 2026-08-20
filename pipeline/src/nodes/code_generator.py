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
    """Extract clean Python code from LLM markdown block."""
    if not raw_code:
        return ""

    pattern = r"```(?:python)?\s*\n?(.*?)\n?```"
    matches = re.findall(pattern, raw_code, re.DOTALL)
    if matches:
        return matches[0].strip()

    cleaned = raw_code.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
    return cleaned


def _build_files_context(
    discovered_tables: List[Dict[str, Any]],
    column_mapping: Dict[str, str],
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
    error_traceback = state.get("error_traceback")
    retry_count = state.get("retry_count", 0)

    # Extract parsed query fields
    muc_tieu = parsed_query.get("muc_tieu", "trich_xuat")
    noi_dung = parsed_query.get("noi_dung", "")
    ten_cong_ty = parsed_query.get("ten_cong_ty", "")
    so_nam = parsed_query.get("so_nam", [])
    tieu_chi_phu = parsed_query.get("tieu_chi_phu")

    # Get column names from mapping
    label_col = column_mapping.get("label_column", "CHỈ TIÊU")
    value_col = column_mapping.get("value_column", "Năm nay")

    # Build files context
    files_context = _build_files_context(discovered_tables, column_mapping)

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

            sample_labels = []
            if discovered_tables:
                from pathlib import Path
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
                error_traceback=error_traceback,
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