"""Node 3: Schema Mapper Node.
Maps natural language column terms from parsed_query to actual DataFrame columns using fuzzy matching and LLM context.
"""

import time
import yaml
from typing import Dict, Any, Optional
from thefuzz import process, fuzz
from langchain_core.messages import SystemMessage, HumanMessage

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.llm_provider import get_llm
from pipeline.src.utils.json_repair import safe_parse_json


def load_schema_mapper_prompt(cfg: Config) -> Dict[str, Any]:
    """Load prompt templates from YAML."""
    prompt_path = cfg.get_prompt_path("schema_mapper.yaml")
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at: {prompt_path}")

    with open(prompt_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fuzzy_match_columns(query_terms: list, actual_columns: list, cutoff: int = 70) -> Dict[str, str]:
    """Perform fuzzy matching between user query column terms and actual CSV columns."""
    mapping = {}
    for term in query_terms:
        if not term:
            continue
        match, score = process.extractOne(term, actual_columns, scorer=fuzz.token_set_ratio)
        if score >= cutoff:
            mapping[term] = match
    return mapping


def schema_mapper_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 3: Map query details/columns to actual table schema columns.
    
    Args:
        state: Current AgentState containing 'parsed_query' and 'table_schema'
        cfg: Config instance

    Returns:
        Updated AgentState with 'column_mapping'
    """
    cfg = cfg or default_config
    start_time = time.time()

    parsed_query = state.get("parsed_query", {})
    table_schema = state.get("table_schema", {})
    actual_columns = list(table_schema.get("columns", {}).keys())

    if not actual_columns:
        return {
            **state,
            "status": "error",
            "error_message": "Không tìm thấy siêu dữ liệu cột (columns) trong schema.",
            "column_mapping": {},
        }

    # Step 1: Extract query column candidates
    query_details = parsed_query.get("query_details", [])
    requested_terms = []
    for d in query_details:
        if isinstance(d, dict) and "column_name" in d:
            requested_terms.append(d["column_name"])
        elif isinstance(d, str):
            requested_terms.append(d)

    # Step 2: Try fuzzy matching first for high-confidence direct matches
    fuzzy_mapping = fuzzy_match_columns(requested_terms, actual_columns, cutoff=80)

    # If fuzzy matching found all terms, use fuzzy_mapping directly
    if len(fuzzy_mapping) == len(requested_terms) and requested_terms:
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["schema_mapper"] = round(latency, 3)
        return {
            **state,
            "column_mapping": fuzzy_mapping,
            "status": "pending",
            "node_latencies": node_latencies,
        }

    # Step 3: Call LLM for semantic schema mapping fallback
    try:
        prompt_data = load_schema_mapper_prompt(cfg)
        system_prompt = prompt_data["system_prompt"]
        json_schema = prompt_data["json_schema"]
        few_shots = prompt_data.get("few_shot_examples", [])

        messages = [
            SystemMessage(content=f"{system_prompt}\n\nSchema Yêu Cầu JSON:\n{json_schema}")
        ]

        for ex in few_shots:
            messages.append(HumanMessage(content=f"User Query: {ex['user_query']}\nSchema: {ex['table_schema']}"))
            messages.append(SystemMessage(content=ex["parsed_output"]))

        # Get the first row (headers) from the sample rows to map numeric columns
        sample_rows = table_schema.get("sample_rows", [])
        header_row = sample_rows[0] if sample_rows else {}

        print(f"🔍 [Schema Mapper] Tiến hành ánh xạ các cột...")
        print(f"   - Cột thực tế: {actual_columns}")
        if header_row:
            print(f"   - Nhãn tương ứng hàng đầu tiên: {header_row}")

        messages.append(
            HumanMessage(
                content=f"Yêu cầu: {state.get('user_query', '')}\n"
                        f"Parsed Intent: {parsed_query}\n"
                        f"Cột thực tế trong dữ liệu: {actual_columns}\n"
                        f"Giá trị thực tế ở dòng đầu tiên (Dòng tiêu đề): {header_row}"
            )
        )

        llm = get_llm(cfg=cfg, temperature=0.0)
        response = llm.invoke(messages)
        raw_text = response.content if isinstance(response.content, str) else str(response.content)

        # Extract and print thoughts
        import re
        think_match = re.search(r"<think>(.*?)</think>", raw_text, re.DOTALL)
        if think_match:
            thought = think_match.group(1).strip()
            indented_thought = thought.replace('\n', '\n  ')
            print(f"💭 [Tư duy - Schema Mapper]:\n  {indented_thought}")
        else:
            json_start = raw_text.find("{")
            if json_start > 10:
                thought = raw_text[:json_start].strip()
                indented_thought = thought.replace('\n', '\n  ')
                print(f"💭 [Tư duy - Schema Mapper]:\n  {indented_thought}")

        parsed_res = safe_parse_json(raw_text)
        llm_mapping = parsed_res.get("column_mapping", {})

        # Merge fuzzy_mapping with llm_mapping (fuzzy takes precedence for exact hits)
        final_mapping = {**llm_mapping, **fuzzy_mapping}

        print(f"📊 [Kết quả - Schema Mapper]: Ánh xạ cột cuối cùng = {final_mapping}\n")

        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["schema_mapper"] = round(latency, 3)

        return {
            **state,
            "column_mapping": final_mapping,
            "status": "pending",
            "node_latencies": node_latencies,
        }

    except Exception as e:
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["schema_mapper"] = round(latency, 3)

        return {
            **state,
            "column_mapping": fuzzy_mapping,
            "status": "pending",  # Fallback to fuzzy_mapping instead of failing completely
            "node_latencies": node_latencies,
        }
