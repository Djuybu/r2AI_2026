"""Unit tests for AST Sandbox Executor Node."""

import pytest
import pandas as pd
from pipeline.src.nodes.executor import executor_node, validate_ast, SecurityError


def test_validate_ast_valid():
    valid_code = "import pandas as pd\ndf = pd.read_csv(file_path)\nresult = df.sum()"
    validate_ast(valid_code)  # Should not raise exception


def test_validate_ast_security_error():
    forbidden_code = "import os\nos.system('rm -rf /')"
    with pytest.raises(SecurityError):
        validate_ast(forbidden_code)


def test_executor_node_success(tmp_path):
    # Create sample CSV
    csv_file = tmp_path / "sales.csv"
    df = pd.DataFrame({"Category": ["A", "B", "A"], "Revenue": [100, 200, 150]})
    df.to_csv(csv_file, index=False)

    state = {
        "generated_code": "import pandas as pd\ndf = pd.read_csv(file_path)\nresult = df.groupby('Category')['Revenue'].sum().reset_index()",
        "matched_table_path": str(csv_file),
        "retry_count": 0,
    }

    output = executor_node(state)
    assert output["status"] == "success"
    assert output["error_traceback"] is None
    assert output["execution_result"]["type"] == "dataframe"
    assert len(output["execution_result"]["data"]) == 2


def test_executor_node_syntax_error():
    state = {
        "generated_code": "df = pd.read_csv(file_path) result = df.sum(",
        "matched_table_path": "dummy.csv",
        "retry_count": 0,
    }

    output = executor_node(state)
    assert output["status"] == "error"
    assert output["error_traceback"] is not None
    assert output["retry_count"] == 1
