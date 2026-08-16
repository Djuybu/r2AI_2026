"""Node 5: AST Sandbox & Execution Node.
Executes generated Pandas code safely inside a restricted AST sandbox environment.
"""

import ast
import sys
import time
import traceback
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config


class SecurityError(Exception):
    """Raised when generated code contains forbidden AST nodes."""
    pass


FORBIDDEN_AST_NODES = (
    ast.Import,
    ast.ImportFrom,
)

FORBIDDEN_BUILTINS = {
    "eval", "exec", "__import__", "open", "compile",
    "globals", "locals", "input", "breakpoint"
}

ALLOWED_MODULES = {"pandas", "pd", "numpy", "np", "datetime", "math", "re"}


def validate_ast(code_str: str) -> None:
    """Validate Python code against AST safety rules."""
    tree = ast.parse(code_str)

    for node in ast.walk(tree):
        # Check forbidden imports unless in ALLOWED_MODULES
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_MODULES:
                    raise SecurityError(f"Importing forbidden module: '{alias.name}'")

        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] not in ALLOWED_MODULES:
                raise SecurityError(f"Importing from forbidden module: '{node.module}'")

        # Check forbidden built-in function calls
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_BUILTINS:
                raise SecurityError(f"Call to forbidden function: '{node.func.id}'")


def format_result(result: Any) -> Any:
    """Format DataFrame, Series, or scalar result for JSON serialization."""
    if isinstance(result, pd.DataFrame):
        # Limit rows for output size
        df_sub = result.head(100)
        return {
            "type": "dataframe",
            "shape": list(result.shape),
            "columns": list(result.columns),
            "data": df_sub.to_dict(orient="records"),
        }
    elif isinstance(result, pd.Series):
        s_sub = result.head(100)
        return {
            "type": "series",
            "name": str(result.name) if result.name else "result",
            "data": s_sub.to_dict(),
        }
    elif isinstance(result, (int, float, str, bool, list, dict)):
        return {
            "type": "scalar",
            "data": result,
        }
    else:
        return {
            "type": "other",
            "data": str(result),
        }


def executor_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 5: Safely execute generated Pandas code and capture result.
    
    Args:
        state: Current AgentState containing 'generated_code' and 'matched_table_path'
        cfg: System Config

    Returns:
        Updated AgentState with 'execution_result', 'error_traceback', and 'retry_count'
    """
    cfg = cfg or default_config
    start_time = time.time()

    code_str = state.get("generated_code", "").strip()
    discovered_tables = state.get("discovered_tables", [])
    file_path = ""
    if discovered_tables:
        file_path = discovered_tables[0].get("csv_path", "")
    retry_count = state.get("retry_count", 0)

    if not code_str:
        return {
            **state,
            "status": "error",
            "error_traceback": "No code generated to execute.",
            "retry_count": retry_count + 1,
        }

    try:
        # Step 1: Validate AST
        validate_ast(code_str)

        print(f"⚙️ [Executor] Đang thực thi mã Pandas...")
        
        # Preload df safely to handle 'NameError: name df is not defined'
        df_loaded = None
        if file_path:
            try:
                df_loaded = pd.read_csv(file_path) if file_path.endswith('.csv') else pd.read_excel(file_path)
            except Exception as e:
                print(f"⚠️ [Executor] Không thể tự động load DataFrame: {e}")

        # Step 2: Prepare execution scope
        exec_globals = {
            "pd": pd,
            "np": np,
            "pandas": pd,
            "numpy": np,
            "file_path": file_path,
            "df": df_loaded,
        }
        # Step 3: Execute code with unified globals/locals dict to resolve function scoping in exec
        exec(code_str, exec_globals)

        # Retrieve result variable
        result_val = exec_globals.get("result")

        if result_val is None:
            # If result wasn't explicitly assigned, check if last expression was evaluated
            raise ValueError("Biến `result` không được tìm thấy sau khi thực thi mã.")

        formatted = format_result(result_val)
        
        print(f"✅ [Executor] Thực thi THÀNH CÔNG!")
        import json
        print(f"📊 [Kết quả - Executor]:\n{json.dumps(formatted, indent=4, ensure_ascii=False)}\n")

        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["executor"] = round(latency, 3)

        return {
            **state,
            "execution_result": formatted,
            "error_traceback": None,
            "status": "success",
            "node_latencies": node_latencies,
        }

    except Exception as e:
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["executor"] = round(latency, 3)

        tb_str = traceback.format_exc()

        return {
            **state,
            "status": "error",
            "error_traceback": tb_str,
            "retry_count": retry_count + 1,
            "node_latencies": node_latencies,
        }
