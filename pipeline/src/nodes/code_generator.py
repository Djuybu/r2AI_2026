"""Node 4: Code Generation & Reflection Node.
Generates executable Python/Pandas code based on intent, column mapping, and error tracebacks during reflection loops.
"""

import re
import time
import yaml
from typing import Dict, Any, Optional
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

            sample_rows = table_schema.get("sample_rows", [])
            header_row = sample_rows[0] if sample_rows else {}

            print(f"🔍 [Code Generator] Tiến hành sinh mã Python (Lần đầu)...")
            print(f"   - Cột thực tế: {table_schema.get('columns', [])}")
            if header_row:
                print(f"   - Nhãn thực tế hàng đầu tiên: {header_row}")
            print(f"   - Ánh xạ cột: {column_mapping}")

            messages.append(
                HumanMessage(
                    content=f"Yêu cầu người dùng: {user_query}\n"
                            f"Đường dẫn file: {file_path}\n"
                            f"Cột thực tế trong dữ liệu: {table_schema.get('columns', [])}\n"
                            f"Nhãn thực tế dòng đầu tiên (Dòng tiêu đề): {header_row}\n"
                            f"Ánh xạ cột (Column Mapping): {column_mapping}\n"
                            f"Hãy tạo mã Python/Pandas lưu kết quả cuối cùng vào biến `result`."
                )
            )

        # Scenario B: Reflection Debugging Loop (retry_count > 0)
        else:
            prompt_data = load_yaml_prompt(cfg, "reflection.yaml")
            system_prompt = prompt_data["system_prompt"]

            print(f"🔄 [Reflection Loop] Đang sửa lỗi mã nguồn (Lần {retry_count})...")
            print(f"   - Traceback Lỗi:\n{error_traceback.strip()}")

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=f"Yêu cầu người dùng: {user_query}\n"
                            f"Đường dẫn file: {file_path}\n"
                            f"Mã Python bị lỗi trước đó:\n```python\n{state.get('generated_code', '')}\n```\n\n"
                            f"Traceback Lỗi:\n{error_traceback}\n\n"
                            f"Hãy sửa lại đoạn mã trên, đảm bảo kết quả cuối cùng lưu vào biến `result`."
                )
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
