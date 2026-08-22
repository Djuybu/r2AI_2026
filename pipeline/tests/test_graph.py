"""Unit tests for LangGraph StateGraph workflow construction."""

from pipeline.src.graph import create_cocopila_graph, route_after_discovery, route_after_execution
from langgraph.graph import END


def test_graph_creation():
    graph = create_cocopila_graph()
    assert graph is not None


def test_routing_logic():
    # Discovery error routing
    assert route_after_discovery({"status": "error"}) == END
    assert route_after_discovery({"status": "pending"}) == "code_generator"

    # Execution success routing
    assert route_after_execution({"status": "success", "retry_count": 0}) == END
    assert route_after_execution({"status": "error", "retry_count": 1}) == "code_generator"
    assert route_after_execution({"status": "error", "retry_count": 3}) == END
