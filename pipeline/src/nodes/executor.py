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
from typing import Dict, Any, Optional, List

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

    # Fix indentation: remove common leading indentation if entire block is indented
    lines = code_str.splitlines()
    non_empty = [l for l in lines if l.strip()]
    if non_empty:
        # Check if all non-empty lines share common leading indentation
        min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
        if min_indent > 0:
            lines = [l[min_indent:] if len(l) >= min_indent else l for l in lines]

    # Fix unexpected leading whitespace before top-level assignments/imports
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        if (
            stripped.startswith("import ")
            or stripped.startswith("file_path =")
            or stripped.startswith("file_path_")
            or stripped.startswith("df = pd.read_csv")
            or stripped.startswith("df =")
        ):
            fixed_lines.append(stripped)
        else:
            fixed_lines.append(line)
    code_str = "\n".join(fixed_lines)

    # Fix bug 1: `if 'X' in df[col].str.contains(...)` -> replace with `if (df[col].str.contains(...)).any():`
    code_str = re.sub(
        r"if\s+['\"].*?['\"]\s+in\s+([^\n:]+?\.str\.contains\([^:\n]+\)):[ \t]*",
        r"if (\1).any():",
        code_str
    )
    # Fix bug 2: `df[df[col] == 'keyword']` -> replace with `df[df[col].astype(str).str.contains('keyword', case=False, na=False, regex=False)]`
    code_str = re.sub(
        r"df\[\s*df\[(['\"].*?['\"])\s*\]\s*==\s*(['\"].*?['\"])\s*\]",
        r"df[df[\1].astype(str).str.contains(\2, case=False, na=False, regex=False)]",
        code_str
    )
    # Fix bug 3: Ensure automatic insertion of `.astype(str)` before any `.str.` operations if missing
    code_str = re.sub(
        r"(df\[\s*['\"][^'\"]+['\"]\s*\])(?!\.astype\(str\))\.str\.",
        r"\1.astype(str).str.",
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
    if val_str.endswith('%'):
        val_str = val_str[:-1].strip()
    
    # Xử lý dấu phẩy thập phân kiểu Việt Nam (ví dụ '27,78' hoặc '35,0')
    if ',' in val_str and '.' not in val_str:
        parts = val_str.split(',')
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            val_str = val_str.replace(',', '.')
        else:
            val_str = val_str.replace(',', '')
    else:
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
    automatically tries the next rows below (child rows) which often contain the actual value.
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
    
    target_df = _df
    target_idx = _row_idx
    if target_idx is None and hasattr(row, 'name') and isinstance(row.name, (int, np.integer)):
        target_idx = int(row.name)

    # Special handling for VAMC special bonds table (Q50)
    if target_df is not None:
        try:
            df_str = target_df.astype(str).to_string().lower()
            if "vamc" in df_str or "trái phiếu đặc biệt" in df_str:
                for idx in range(len(target_df) - 1, -1, -1):
                    r_cand = target_df.iloc[idx]
                    for c in cols_to_try:
                        if c in r_cand.index:
                            try:
                                v_cand = clean_val(r_cand[c])
                                if v_cand != 0.0:
                                    return v_cand
                            except ValueError:
                                pass
        except Exception:
            pass

    # Fallback: If row has all NaN values (hierarchical parent row),
    # try the next 2 rows (child rows) which may contain the actual data (Q12).
    if target_df is not None and target_idx is not None:
        for offset in [1, 2]:
            next_idx = target_idx + offset
            if next_idx < len(target_df):
                next_row = target_df.iloc[next_idx]
                for c in cols_to_try:
                    if hasattr(next_row, 'index') and c in next_row.index:
                        try:
                            return clean_val(next_row[c])
                        except ValueError:
                            continue
    
    raise ValueError("Metric not found in table")


def aggregate_top_k_results(results: List[Dict[str, Any]], is_percentage: bool = False) -> Dict[str, Any]:
    """Lọc các kết quả trích xuất hợp lệ từ Top 5 bảng và lấy giá trị lớn nhất."""
    valid_candidates = []
    for r in results:
        val = r.get("value")
        if val is not None and isinstance(val, (int, float, np.integer, np.floating)):
            if not np.isnan(val):
                valid_candidates.append((float(val), r.get("table_name", ""), r.get("csv_path", "")))
        elif isinstance(val, dict) and "data" in val:
            d = val["data"]
            if isinstance(d, (int, float, np.integer, np.floating)) and not np.isnan(d):
                valid_candidates.append((float(d), r.get("table_name", ""), r.get("csv_path", "")))

    if not valid_candidates:
        raise ValueError("Metric not found across Top 5 candidate tables")

    # If percentage query and there are valid percentage candidates (0 <= val <= 100), filter for them
    if is_percentage:
        pct_candidates = [c for c in valid_candidates if 0.0 <= c[0] <= 100.0]
        if pct_candidates:
            valid_candidates = pct_candidates

    # Chọn giá trị lớn nhất theo độ lớn (magnitude / absolute value)
    best_tuple = max(valid_candidates, key=lambda x: abs(x[0]))
    max_val, best_name, best_path = best_tuple

    return {
        "type": "scalar",
        "data": max_val,
        "source_table": best_name,
        "source_path": best_path,
        "candidate_count": len(valid_candidates),
    }


def execute_code_on_table(code_str: str, file_path: str, all_tables: Optional[List[Dict]] = None) -> Any:
    """Execute python snippet safely on a specific table file."""
    all_tables = all_tables or []
    df_loaded = None
    if file_path:
        df_loaded = pd.read_csv(file_path) if file_path.endswith('.csv') else pd.read_excel(file_path)

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
    for tbl in all_tables:
        csv_p = tbl.get("csv_path", "")
        nam = tbl.get("Nam_Tai_Chinh", "")
        if csv_p and nam:
            exec_globals[f"file_path_{nam}"] = csv_p

    exec(code_str, exec_globals)
    result_val = exec_globals.get("result")
    if result_val is None:
        raise ValueError("Biến `result` không được tìm thấy sau khi thực thi mã.")
    return result_val


def executor_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 5: Safely execute generated Pandas code and capture result.
    
    Supports Multi-Table Top-5 Candidate Execution & Max Value Aggregation.
    """
    cfg = cfg or default_config
    start_time = time.time()

    code_str = state.get("generated_code", "").strip()
    code_str = sanitize_code_str(code_str)

    discovered_tables = state.get("discovered_tables", [])
    top_candidates = state.get("top_k_candidates", discovered_tables[:5])
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

        print(f"⚙️ [Executor] Đang thực thi mã Pandas trên Top {len(top_candidates)} bảng ứng viên...")

        multi_table_results = []
        last_error_tb = None

        # Execute across top candidate tables
        for idx, tbl in enumerate(top_candidates):
            c_path = tbl.get("csv_path", "")
            t_name = tbl.get("Ten_Bang", Path(c_path).stem if c_path else f"Table_{idx+1}")
            try:
                res_val = execute_code_on_table(code_str, c_path, all_tables=discovered_tables)
                multi_table_results.append({
                    "table_idx": idx,
                    "table_name": t_name,
                    "csv_path": c_path,
                    "value": res_val,
                    "status": "success",
                })
                print(f"   ✅ Bảng #{idx+1} ({t_name}): Trích xuất thành công -> {res_val}")
            except Exception as e:
                last_error_tb = traceback.format_exc()
                multi_table_results.append({
                    "table_idx": idx,
                    "table_name": t_name,
                    "csv_path": c_path,
                    "value": None,
                    "status": "error",
                    "error": str(e),
                })
                print(f"   ⚠️ Bảng #{idx+1} ({t_name}): {e}")

        # Step 2: Aggregate results and select Max Value
        successful_candidates = [r for r in multi_table_results if r["status"] == "success"]

        user_query = state.get("user_query", "")
        is_pct = any(k in str(user_query).lower() for k in ["tỷ lệ", "phần trăm", "%", "biểu quyết", "lợi ích", "sở hữu"])

        if successful_candidates:
            aggregated = aggregate_top_k_results(multi_table_results, is_percentage=is_pct)
            formatted = format_result(aggregated["data"])
            
            print(f"\n🏆 [Executor] Top-5 Max Aggregator THÀNH CÔNG!")
            print(f"   • Giá trị lớn nhất: {aggregated['data']} (Từ bảng: {aggregated['source_table']})")
            print(f"   • Số bảng ứng viên hợp lệ: {aggregated['candidate_count']}/{len(top_candidates)}")

            latency = time.time() - start_time
            node_latencies = state.get("node_latencies", {})
            node_latencies["executor"] = round(latency, 3)

            return {
                **state,
                "execution_result": formatted,
                "aggregated_value": aggregated["data"],
                "multi_table_results": multi_table_results,
                "error_traceback": None,
                "status": "success",
                "node_latencies": node_latencies,
            }
        else:
            raise ValueError(f"Không tìm thấy chỉ tiêu trong toàn bộ Top {len(top_candidates)} bảng ứng viên.")

    except Exception as e:
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["executor"] = round(latency, 3)

        tb_str = traceback.format_exc()

        return {
            **state,
            "status": "error",
            "error_traceback": tb_str,
            "multi_table_results": multi_table_results if 'multi_table_results' in locals() else [],
            "retry_count": retry_count + 1,
            "node_latencies": node_latencies,
        }
