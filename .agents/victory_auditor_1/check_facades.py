import ast
from pathlib import Path

root = Path("d:/hobby_project/cocopila/r2AI_2026/pipeline/src")

facade_findings = []

for py_file in root.rglob("*.py"):
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check if function body is just 'pass' or 'return constant' (excluding empty stubs in __init__)
            if len(node.body) == 1:
                first = node.body[0]
                if isinstance(first, ast.Pass) and py_file.name != "__init__.py":
                    facade_findings.append((py_file, node.name, "Single 'pass' statement"))
                elif isinstance(first, ast.Return) and isinstance(first.value, ast.Constant):
                    # Check if it's a trivial constant return
                    facade_findings.append((py_file, node.name, f"Single constant return: {first.value.value}"))

print(f"Total facade findings: {len(facade_findings)}")
for f, name, desc in facade_findings:
    print(f"  {f.name} -> {name}(): {desc}")
