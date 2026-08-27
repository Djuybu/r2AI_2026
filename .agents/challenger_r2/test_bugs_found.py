"""
d:/hobby_project/cocopila/r2AI_2026/.agents/challenger_r2/test_bugs_found.py
===========================================================================
Empirical Bug Reproductions Discovered During Adversarial Verification.
"""

import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
import ast
from pipeline.src.nodes.executor import sanitize_code_str, validate_ast


def test_sanitize_code_str_preserves_multiline_if_block():
    r"""
    VERIFICATION OF FIX:
    In executor.py line 93:
        r"if\s+['\"].*?['\"]\s+in\s+([^\n:]+?\.str\.contains\([^:\n]+\)):[ \t]*"
    The trailing `:[ \t]*` only matches horizontal whitespace on the same line,
    preserving the newline after `:` and preventing IndentationError in multiline if blocks.
    """
    original_llm_code = (
        "if 'Tiền' in df['0'].str.contains('Tiền'):\n"
        "    row = df[df['0'].str.contains('Tiền')].iloc[0]\n"
        "    result = 100\n"
    )
    
    sanitized = sanitize_code_str(original_llm_code)
    
    # Observe the sanitized code
    first_line = sanitized.split("\n")[0]
    
    # Asserting that the newline was preserved after the colon:
    assert first_line == "if (df['0'].astype(str).str.contains('Tiền')).any():", "Newline was preserved properly"
    assert "any():row = " not in first_line
    
    # Asserting that this parses cleanly into valid AST without IndentationError:
    tree = ast.parse(sanitized)
    assert tree is not None

