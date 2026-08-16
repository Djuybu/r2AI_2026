"""Node 1: Query Parser Node.
Phân tích câu hỏi tài chính thành cấu trúc JSON chuẩn.
Output format mới: muc_tieu, noi_dung, ten_cong_ty, so_nam, tieu_chi_phu.
Không thực hiện tìm bảng — việc này do Data Discovery xử lý.
"""

import re
import time
import yaml
from typing import Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.llm_provider import get_llm
from pipeline.src.utils.json_repair import safe_parse_json


def load_query_parser_prompt(cfg: Config) -> Dict[str, Any]:
    """Load prompt templates and few-shot examples from YAML."""
    prompt_path = cfg.get_prompt_path("query_parser.yaml")
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at: {prompt_path}")

    with open(prompt_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_query_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 1: Phân tích câu hỏi thành cấu trúc truy vấn.

    Trích xuất: muc_tieu, noi_dung, ten_cong_ty, so_nam, tieu_chi_phu.
    KHÔNG tìm bảng — Data Discovery sẽ xử lý.

    Args:
        state: Current AgentState containing 'user_query'
        cfg: Config instance (defaults to global config)

    Returns:
        Updated AgentState with 'parsed_query', 'status', and latency tracking.
    """
    cfg = cfg or default_config
    start_time = time.time()
    user_query = state.get("user_query", "").strip()

    if not user_query:
        return {
            **state,
            "status": "error",
            "error_message": "User query is empty.",
            "parsed_query": {},
        }

    try:
        # Load prompts
        prompt_data = load_query_parser_prompt(cfg)
        system_prompt = prompt_data["system_prompt"]
        json_schema = prompt_data["json_schema"]
        few_shots = prompt_data.get("few_shot_examples", [])

        # Build prompt messages
        prompt_messages = [
            SystemMessage(content=f"{system_prompt}\n\nSchema Yêu cầu:\n{json_schema}")
        ]

        for example in few_shots:
            prompt_messages.append(HumanMessage(content=example["user_query"]))
            prompt_messages.append(SystemMessage(content=example["parsed_output"]))

        prompt_messages.append(HumanMessage(content=f"Câu hỏi: {user_query}"))

        # Call LLM
        llm = get_llm(cfg=cfg, temperature=0.0)
        response = llm.invoke(prompt_messages)

        raw_content = response.content if isinstance(response.content, str) else str(response.content)

        # Extract and print agent thoughts
        print(f"\n🔍 [Query Parser] Đang phân tích câu hỏi: '{user_query}'")
        think_match = re.search(r"<think>(.*?)</think>", raw_content, re.DOTALL)
        if think_match:
            thought = think_match.group(1).strip()
            indented_thought = thought.replace('\n', '\n  ')
            print(f"💭 [Tư duy - Query Parser]:\n  {indented_thought}")
        else:
            json_start = raw_content.find("{")
            if json_start > 10:
                thought = raw_content[:json_start].strip()
                indented_thought = thought.replace('\n', '\n  ')
                print(f"💭 [Tư duy - Query Parser]:\n  {indented_thought}")

        # Parse output JSON
        parsed_json = safe_parse_json(raw_content)

        # Ensure minimal structure with new fields
        if "muc_tieu" not in parsed_json:
            parsed_json["muc_tieu"] = "trich_xuat"
        if "noi_dung" not in parsed_json:
            parsed_json["noi_dung"] = ""
        if "ten_cong_ty" not in parsed_json:
            parsed_json["ten_cong_ty"] = ""
        if "so_nam" not in parsed_json:
            parsed_json["so_nam"] = []
        if "tieu_chi_phu" not in parsed_json:
            parsed_json["tieu_chi_phu"] = None

        # Ensure so_nam is always a list
        if isinstance(parsed_json["so_nam"], str):
            parsed_json["so_nam"] = [parsed_json["so_nam"]]
        elif isinstance(parsed_json["so_nam"], (int, float)):
            parsed_json["so_nam"] = [str(int(parsed_json["so_nam"]))]

        print(
            f"📊 [Kết quả - Query Parser]:\n"
            f"   Mục tiêu: {parsed_json.get('muc_tieu')}\n"
            f"   Nội dung: {parsed_json.get('noi_dung')}\n"
            f"   Công ty: {parsed_json.get('ten_cong_ty')}\n"
            f"   Năm: {parsed_json.get('so_nam')}\n"
            f"   Tiêu chí phụ: {parsed_json.get('tieu_chi_phu')}\n"
        )

        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["query_parser"] = round(latency, 3)

        return {
            **state,
            "parsed_query": parsed_json,
            "status": "pending",
            "node_latencies": node_latencies,
        }

    except Exception as e:
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["query_parser"] = round(latency, 3)

        return {
            **state,
            "status": "error",
            "error_message": f"Query parser node error: {str(e)}",
            "parsed_query": {},
            "node_latencies": node_latencies,
        }
