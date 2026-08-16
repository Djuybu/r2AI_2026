"""Node 3: Schema Mapper Node.
Maps natural language column terms from parsed_query to actual DataFrame columns using fuzzy matching and LLM context.
"""

import time
import yaml
from pathlib import Path
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


def map_schema_columns(user_query: str, parsed_query: Dict[str, Any], table_schema: Dict[str, Any], cfg: Config) -> Dict[str, str]:
    """Map user query columns to actual columns in table_schema."""
    actual_columns = list(table_schema.get("columns", {}).keys())

    if not actual_columns:
        return {}

    # Step 1: Extract query column candidates
    query_details = parsed_query.get("query_details", [])
    requested_terms = []
    for d in query_details:
        if isinstance(d, dict) and "column_name" in d:
            requested_terms.append(d["column_name"])
        elif isinstance(d, str):
            requested_terms.append(d)

    # Step 1.5: Check if this is a financial statement table structure (pivot-like schema)
    label_col = None
    value_col = None
    
    for c in ["CHÍ TIÊU", "CHỈ TIÊU", "TÀI SẢN", "NGUỒN VỐN", "Cột_0", "Mã số"]:
        if c in actual_columns:
            label_col = c
            break
            
    for c in ["Năm nay", "Số đầu năm", "Số cuối năm", "Năm trước"]:
        if c in actual_columns:
            value_col = c
            break
            
    if not label_col and "0" in actual_columns:
        label_col = "0"
    if not value_col and "1" in actual_columns:
        value_col = "1"
        
    if label_col and value_col:
        print(f"📊 [Schema Mapper] Phát hiện cấu trúc Báo cáo Tài chính: Nhãn='{label_col}', Giá trị='{value_col}'")
        mapping = {}
        terms = requested_terms if requested_terms else ["chỉ tiêu"]
        for term in terms:
            mapping[term] = label_col
        mapping["giá trị"] = value_col
        mapping["số tiền"] = value_col
        return mapping

    # Step 2: Try fuzzy matching first for high-confidence direct matches
    fuzzy_mapping = fuzzy_match_columns(requested_terms, actual_columns, cutoff=80)

    # If fuzzy matching found all terms, use fuzzy_mapping directly
    if len(fuzzy_mapping) == len(requested_terms) and requested_terms:
        return fuzzy_mapping

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

        messages.append(
            HumanMessage(
                content=f"Yêu cầu: {user_query}\n"
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

        # Merge fuzzy_mapping with llm_mapping
        return {**llm_mapping, **fuzzy_mapping}

    except Exception as e:
        print(f"⚠️ LLM column mapping failed: {e}. Falling back to fuzzy matching.")
        return fuzzy_mapping


def schema_mapper_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 3: Map query details/columns to actual table schema columns.
    
    Args:
        state: Current AgentState containing 'parsed_query' and 'table_schema'
        cfg: Config instance

    Returns:
        Updated AgentState with 'column_mappings' and 'column_mapping'
    """
    cfg = cfg or default_config
    start_time = time.time()

    matched_table_paths = state.get("matched_table_paths", {})
    table_schemas = state.get("table_schemas", {})
    parsed_query = state.get("parsed_query", {})
    user_query = state.get("user_query", "")

    column_mappings = {}

    if matched_table_paths:
        print(f"🔍 [Schema Mapper] Tiến hành ánh xạ các cột cho {len(matched_table_paths)} file...")
        for year, file_path in matched_table_paths.items():
            schema = table_schemas.get(file_path, {})
            if schema:
                mapping = map_schema_columns(user_query, parsed_query, schema, cfg)
                column_mappings[file_path] = mapping
                print(f"   - File {Path(file_path).name} (Năm {year}) mapping: {mapping}")
    else:
        matched_table_path = state.get("matched_table_path")
        table_schema = state.get("table_schema", {})
        if matched_table_path and table_schema:
            print(f"🔍 [Schema Mapper] Tiến hành ánh xạ các cột cho file duy nhất...")
            mapping = map_schema_columns(user_query, parsed_query, table_schema, cfg)
            column_mappings[matched_table_path] = mapping
            print(f"   - File {Path(matched_table_path).name} mapping: {mapping}")

    # Set singular fields for compatibility
    first_mapping = {}
    if column_mappings:
        first_mapping = list(column_mappings.values())[0]

    latency = time.time() - start_time
    node_latencies = state.get("node_latencies", {})
    node_latencies["schema_mapper"] = round(latency, 3)

    return {
        **state,
        "column_mappings": column_mappings,
        "column_mapping": first_mapping,
        "status": "pending",
        "node_latencies": node_latencies,
    }
