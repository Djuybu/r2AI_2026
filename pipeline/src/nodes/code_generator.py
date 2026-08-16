"""Node 4: Code Generation & Reflection Node.
Generates executable Python/Pandas code based on intent, column mapping, and error tracebacks during reflection loops.
"""

import re
import time
import yaml
from typing import Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

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

    # Match ```python ... ``` or ``` ... ```
    pattern = r"```(?:python)?\s*\n?(.*?)\n?```"
    matches = re.findall(pattern, raw_code, re.DOTALL)
    if matches:
        return matches[0].strip()

    # If no markdown block, clean trailing quotes
    cleaned = raw_code.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
    return cleaned


def code_generator_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 4: Generate Pandas code or fix previously failed code (Reflection Loop).
    
    Args:
        state: Current AgentState containing user_query, column_mapping, table_schema, error_traceback
        cfg: Config instance

    Returns:
        Updated AgentState with 'generated_code'
    """
    cfg = cfg or default_config
    start_time = time.time()

    user_query = state.get("user_query", "")
    file_path = state.get("matched_table_path", "")
    table_schema = state.get("table_schema", {})
    column_mapping = state.get("column_mapping", {})
    error_traceback = state.get("error_traceback")
    retry_count = state.get("retry_count", 0)

    # Build context for all matched files
    matched_table_paths = state.get("matched_table_paths", {})
    table_schemas = state.get("table_schemas", {})
    column_mappings = state.get("column_mappings", {})

    files_context = ""
    if matched_table_paths and len(matched_table_paths) > 1:
        lines = ["Chúng tôi có dữ liệu của nhiều năm như sau:"]
        for y, path in sorted(matched_table_paths.items()):
            schema = table_schemas.get(path, {})
            mapping = column_mappings.get(path, {})
            cols = list(schema.get("columns", {}).keys())
            sample = schema.get("sample_rows", [{}])[0] if schema.get("sample_rows") else {}
            lines.append(
                f"- Năm {y}:\n"
                f"  Đường dẫn file (dùng trong code): '{path}'\n"
                f"  Cột thực tế trong file: {cols}\n"
                f"  Dòng đầu tiên: {sample}\n"
                f"  Ánh xạ cột (Column Mapping): {mapping}\n"
            )
        files_context = "\n".join(lines)
    else:
        cols = list(table_schema.get("columns", {}).keys())
        sample = table_schema.get("sample_rows", [{}])[0] if table_schema.get("sample_rows") else {}
        files_context = (
            f"Đường dẫn file (dùng trong code): '{file_path}'\n"
            f"Cột thực tế trong file: {cols}\n"
            f"Dòng đầu tiên: {sample}\n"
            f"Ánh xạ cột (Column Mapping): {column_mapping}"
        )

    try:
        # Scenario A: Initial Code Generation (retry_count == 0)
        if not error_traceback or retry_count == 0:
            prompt_data = load_yaml_prompt(cfg, "code_generator.yaml")
            system_prompt = prompt_data["system_prompt"]
            few_shots = prompt_data.get("few_shot_examples", [])

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
            # Build specific financial statement instructions in English to avoid UTF-8 protobuf issues
            paths_str = ""
            if matched_table_paths:
                for y, path in sorted(matched_table_paths.items()):
                    escaped_path = path.replace('\\', '\\\\')
                    paths_str += f"file_path_{y} = '{escaped_path}'\n"
            else:
                escaped_path = file_path.replace('\\', '\\\\')
                paths_str = f"file_path = '{escaped_path}'"

            # Determine label and value columns
            label_col = "CHÍ TIÊU"
            val_col = "Năm nay"
            if column_mapping:
                for v in column_mapping.values():
                    if v in ["CHÍ TIÊU", "CHỈ TIÊU", "TÀI SẢN", "NGUỒN VỐN", "Cột_0", "Mã số"]:
                        label_col = v
                        break
                for k, v in column_mapping.items():
                    if k in ["giá trị", "số tiền", "Năm nay", "Năm trước", "Số cuối năm", "Số đầu năm"]:
                        val_col = v
                        break

            human_content = (
                f"Yêu cầu người dùng: {user_query}\n\n"
                f"{files_context}\n\n"
                f"🚨 IMPORTANT FINANCIAL STATEMENT RULES:\n"
                f"1. This is a financial statement pivot table where:\n"
                f"   - Column '{label_col}' contains the names/labels of the accounts (e.g. 'Tiền và các khoản tương đương tiền', 'Doanh thu thuần').\n"
                f"   - Column '{val_col}' contains the numeric values (represented as strings with dots like '382.666' or parentheses for negative values).\n"
                f"2. To extract the value for any item (e.g., 'tổng tiền', 'tiền và các khoản tương đương tiền'), you MUST:\n"
                f"   - Filter the row using `.str.contains` on column '{label_col}':\n"
                f"     row = df[df['{label_col}'].str.contains('tiền', case=False, na=False)]\n"
                f"   - Extract the raw string value from column '{val_col}':\n"
                f"     raw_val = row['{val_col}'].values[0]\n"
                f"   - Parse it using the clean_val helper to convert it to a float.\n"
                f"3. You MUST read each file path explicitly. Use these variables directly in your code:\n"
                f"{paths_str}\n"
                f"4. Write code to:\n"
                f"   - Define a helper function `clean_val(val)` to clean the numeric strings:\n"
                f"     def clean_val(val):\n"
                f"         if pd.isna(val) or str(val).strip() in ['-', '', 'nan', 'NaN']:\n"
                f"             return 0.0\n"
                f"         val_str = str(val).strip().replace('.', '')\n"
                f"         if '(' in val_str and ')' in val_str:\n"
                f"             val_str = '-' + val_str.replace('(', '').replace(')', '')\n"
                f"         return float(val_str)\n"
                f"   - Read each year's file using pd.read_csv.\n"
                f"   - Find the target row in column '{label_col}' (e.g. searching for a relevant keyword like 'tiền' for cash/money questions, or 'doanh thu' for revenue questions).\n"
                f"   - Extract and clean the target value from column '{val_col}' for each year.\n"
                f"   - Calculate the final result (e.g. for growth rate from 2019 to 2021, compute (val_2021 - val_2019) / val_2019 * 100).\n"
                f"   - Assign the final numeric result (float) to the variable `result`."
            )
            messages.append(HumanMessage(content=human_content))

        # Scenario B: Reflection Debugging Loop (retry_count > 0)
        else:
            prompt_data = load_yaml_prompt(cfg, "reflection.yaml")
            system_prompt = prompt_data["system_prompt"]

            print(f"🔄 [Reflection Loop] Đang sửa lỗi mã nguồn (Lần {retry_count})...")
            print(f"   - Traceback Lỗi:\n{error_traceback.strip()}")

            # Determine label and value columns
            label_col = "CHÍ TIÊU"
            val_col = "Năm nay"
            if column_mapping:
                for v in column_mapping.values():
                    if v in ["CHÍ TIÊU", "CHỈ TIÊU", "TÀI SẢN", "NGUỒN VỐN", "Cột_0", "Mã số"]:
                        label_col = v
                        break
                for k, v in column_mapping.items():
                    if k in ["giá trị", "số tiền", "Năm nay", "Năm trước", "Số cuối năm", "Số đầu năm"]:
                        val_col = v
                        break

            human_content = (
                f"Yêu cầu người dùng: {user_query}\n\n"
                f"{files_context}\n\n"
                f"Mã Python bị lỗi trước đó:\n```python\n{state.get('generated_code', '')}\n```\n\n"
                f"Traceback Lỗi:\n{error_traceback}\n\n"
                f"Hãy sửa lại đoạn mã trên, đảm bảo kết quả cuối cùng lưu vào biến `result`.\n\n"
                f"🚨 FINANCIAL STATEMENT DEBUGGING TIPS:\n"
                f"1. Filter the row using `.str.contains` (e.g. 'tiền' or 'doanh thu' or the target keyword from query) on column '{label_col}'.\n"
                f"2. Extract the value from the value column '{val_col}' and clean it using `clean_val` before calculating.\n"
                f"3. Use the exact absolute file paths from the context; do not formatting paths or loop dynamically.\n"
                f"4. Store the final result in the variable `result`."
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_content)
            ]

        # Call LLM with temperature 0 for deterministic code generation
        llm = get_llm(cfg=cfg, temperature=0.0)
        response = llm.invoke(messages)
        raw_text = response.content if isinstance(response.content, str) else str(response.content)

        # Extract and print thoughts
        import re
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