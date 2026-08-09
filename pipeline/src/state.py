"""State definition for LangGraph workflow in Cocopila."""

from typing import Any, Dict, List, Literal, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """Shared state dictionary passed across LangGraph nodes."""

    # User Input
    user_query: str

    # Node 1: Query Parser Output
    parsed_query: Dict[str, Any]

    # Node 2: Data Discovery Output
    matched_table_path: Optional[str]

    # Node 3: Schema Mapper Output
    table_schema: Dict[str, Any]
    column_mapping: Dict[str, str]

    # Node 4: Code Generator Output
    generated_code: str

    # Node 5: Executor Output
    execution_result: Any
    error_traceback: Optional[str]
    retry_count: int

    # General Workflow Metadata
    status: Literal["pending", "success", "error", "fallback"]
    error_message: Optional[str]
    node_latencies: Dict[str, float]
    llm_token_usage: Dict[str, int]
