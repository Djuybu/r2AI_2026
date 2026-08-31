"""LangGraph StateGraph Definition for Cocopila Pandas Data Agent Pipeline."""

from typing import Literal, Optional
from langgraph.graph import StateGraph, END

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.nodes.query_parser import parse_query_node
from pipeline.src.nodes.data_discovery import data_discovery_node
from pipeline.src.nodes.schema_mapper import schema_mapper_node
from pipeline.src.nodes.code_generator import code_generator_node
from pipeline.src.nodes.executor import executor_node

def route_after_discovery(state: AgentState) -> Literal["schema_mapper", "__end__"]:
    """Route workflow after data discovery node."""
    if state.get("status") == "error":
        return END
    return "schema_mapper"


def route_after_schema_mapper(state: AgentState) -> Literal["code_generator", "__end__"]:
    """Route workflow after schema mapper node."""
    if state.get("status") == "error":
        return END
    return "code_generator"


import time

def route_after_execution(state: AgentState, cfg: Optional[Config] = None) -> Literal["code_generator", "__end__"]:
    """Conditional edge for Reflection Debugging Loop."""
    cfg = cfg or default_config
    status = state.get("status")
    retry_count = state.get("retry_count", 0)
    query_start_time = state.get("query_start_time", 0)
    total_elapsed = time.time() - query_start_time if query_start_time > 0 else 0

    if status == "success":
        return END

    if status == "error":
        if retry_count < cfg.MAX_RETRIES and total_elapsed < 30.0:
            print(f"🔄 Reflection Loop Activated! Retrying code generation ({retry_count}/{cfg.MAX_RETRIES})...")
            return "code_generator"

    return END


def create_cocopila_graph(cfg: Optional[Config] = None):
    """Construct and compile the LangGraph workflow graph."""
    cfg = cfg or default_config

    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("query_parser", lambda state: parse_query_node(state, cfg))
    workflow.add_node("data_discovery", lambda state: data_discovery_node(state, cfg))
    workflow.add_node("schema_mapper", lambda state: schema_mapper_node(state, cfg))
    workflow.add_node("code_generator", lambda state: code_generator_node(state, cfg))
    workflow.add_node("executor", lambda state: executor_node(state, cfg))

    # Define Workflow Edges
    workflow.set_entry_point("query_parser")
    workflow.add_edge("query_parser", "data_discovery")

    workflow.add_conditional_edges(
        "data_discovery",
        route_after_discovery,
        {
            "schema_mapper": "schema_mapper",
            END: END,
        }
    )

    workflow.add_conditional_edges(
        "schema_mapper",
        route_after_schema_mapper,
        {
            "code_generator": "code_generator",
            END: END,
        }
    )

    workflow.add_edge("code_generator", "executor")

    workflow.add_conditional_edges(
        "executor",
        lambda state: route_after_execution(state, cfg),
        {
            "code_generator": "code_generator",
            END: END,
        }
    )

    return workflow.compile()
