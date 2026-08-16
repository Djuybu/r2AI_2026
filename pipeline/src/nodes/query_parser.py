"""Node 1: Query Parser Node.
Standardizes natural language questions into structured JSON intents.
"""

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
    """LangGraph Node 1: Extract intent and parameters from user query.
    
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

        # Build prompt instructions
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
        import re
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

        # Ensure minimal structure
        if "intent" not in parsed_json:
            parsed_json["intent"] = "general"
        if "query_details" not in parsed_json:
            parsed_json["query_details"] = []
        if "file_name" not in parsed_json:
            parsed_json["file_name"] = None

        # Ensure rag_search_query is present; fall back to cleaned user query
        if not parsed_json.get("rag_search_query"):
            import re as _re
            _q = _re.sub(r"\b20\d{2}\b", "", user_query)
            _q = _re.sub(r"\s+", " ", _q).strip()
            parsed_json["rag_search_query"] = _q

        # Ensure required_tables is present with at least one entry
        if not parsed_json.get("required_tables"):
            parsed_json["required_tables"] = ["income_statement"]

        print(f"📊 [Kết quả - Query Parser]: Intent={parsed_json.get('intent')}, File={parsed_json.get('file_name')}, Tables={parsed_json.get('required_tables')}, RAG Query='{parsed_json.get('rag_search_query')}'\n")

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
