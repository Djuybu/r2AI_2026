"""Reproduction script for sanitize_code_str indentation bug."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import traceback
from pipeline.src.nodes.executor import sanitize_code_str, validate_ast

code = """if 'Tiền' in df['0'].str.contains('Tiền'):
    row = df[df['0'].str.contains('Tiền')].iloc[0]
    result = 100
"""

print("--- Original code ---")
print(code)

sanitized = sanitize_code_str(code)
print("--- Sanitized code ---")
print(sanitized)

try:
    validate_ast(sanitized)
    print("validate_ast: PASSED")
except Exception as e:
    print(f"validate_ast: FAILED with error: {type(e).__name__}: {e}")
    traceback.print_exc()

try:
    exec(sanitized, {"df": None})
except Exception as e:
    print(f"exec: FAILED with error: {type(e).__name__}: {e}")
