"""Node 5: AST Sandbox & Execution Node.
Executes generated Pandas code safely inside a restricted AST sandbox environment.
"""

import ast
import re
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


def sanitize_code_str(code_str: str) -> str:
    """Pre-process and fix common LLM-generated code syntax bugs before execution."""
    if not code_str:
        return ""
    # Fix bug 1: `if 'X' in df[col].str.contains(...)` -> replace with `if (df[col].str.contains(...)).any():`
    code_str = re.sub(
        r"if\s+['\"].*?['\"]\s+in\s+([^\n:]+?\.str\.contains\([^:\n]+\)):\s*",
        r"if (\1).any():",
        code_str
    )
    # Fix bug 2: `df[df[col] == 'keyword']` -> replace with `df[df[col].astype(str).str.contains('keyword', case=False, na=False, regex=False)]`
    # because row labels in financial tables often have prefixes like '1. ', '9. ', 'I. '
    code_str = re.sub(
        r"df\[\s*df\[(['\"].*?['\"])\s*\]\s*==\s*(['\"].*?['\"])\s*\]",
        r"df[df[\1].astype(str).str.contains(\2, case=False, na=False, regex=False)]",
        code_str
    )
    return code_str


def clean_val(val):
    if pd.isna(val):
        raise ValueError("Metric not found in table")
    val_str = str(val).strip()
    if val_str in ['-', '—']:
        return 0.0
    if not val_str or val_str in ['', 'nan', 'NaN', 'None', 'null', 'n/a']:
        raise ValueError("Metric not found in table")
    if isinstance(val, (int, float)): return float(val)
    neg = False
    if val_str.startswith('(') and val_str.endswith(')'):
        neg = True
        val_str = val_str[1:-1].strip()
    val_str = val_str.replace(',', '')
    if '.' in val_str:
        parts = val_str.split('.')
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            val_str = val_str.replace('.', '')
    try:
        res = float(val_str)
        return -res if neg else res
    except Exception:
        raise ValueError("Metric not found in table")


def extract_value(row, preferred_col, _df=None, _row_idx=None):
    """Extract a numeric value from a row, trying preferred_col first then fallback columns.
    
    Enhanced: If all columns on the matched row are NaN/empty (hierarchical parent row),
    automatically tries the next row below (child row) which often contains the actual value.
    """
    cols_to_try = [preferred_col, '1', '2', '3', '4', '5']
    
    # Try extracting from the current row first
    for c in cols_to_try:
        if hasattr(row, 'index') and c in row.index:
            try:
                return clean_val(row[c])
            except ValueError:
                continue
        elif isinstance(row, pd.DataFrame) and c in row.columns and not row.empty:
            try:
                return clean_val(row[c].iloc[0])
            except ValueError:
                continue
    
    # Auto-resolve _df and _row_idx if not provided explicitly
    target_df = _df
    target_idx = _row_idx
    if target_idx is None and hasattr(row, 'name') and isinstance(row.name, (int, np.integer)):
        target_idx = int(row.name)

    # Fallback: If row has all NaN values (hierarchical parent row),
    # try the next row (child row) which may contain the actual data.
    if target_df is not None and target_idx is not None:
        next_idx = target_idx + 1
        if next_idx < len(target_df):
            next_row = target_df.iloc[next_idx]
            for c in cols_to_try:
                if hasattr(next_row, 'index') and c in next_row.index:
                    try:
                        return clean_val(next_row[c])
                    except ValueError:
                        continue
    
    raise ValueError("Metric not found in table")


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
    code_str = sanitize_code_str(code_str)

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

        def local_extract_value(row, preferred_col, _df=None, _row_idx=None):
            return extract_value(row, preferred_col, _df=(_df if _df is not None else df_loaded), _row_idx=_row_idx)

        # Step 2: Prepare execution scope
        exec_globals = {
            "pd": pd,
            "np": np,
            "pandas": pd,
            "numpy": np,
            "file_path": file_path,
            "df": df_loaded,
            "clean_val": clean_val,
            "extract_value": extract_value,
        }
        for tbl in discovered_tables:
            csv_p = tbl.get("csv_path", "")
            nam = tbl.get("Nam_Tai_Chinh", "")
            if csv_p:
                if nam:
                    exec_globals[f"file_path_{nam}"] = csv_p
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
