import json
import ast
import sys

nb_path = "notebooks/kaggle_bootstrap.ipynb"
with open(nb_path, "r", encoding="utf-8") as f:
    nb = json.load(f)

for idx, cell in enumerate(nb["cells"]):
    cell_type = cell.get("cell_type")
    src = "".join(cell.get("source", ""))
    if cell_type == "code":
        lines = src.splitlines()
        py_lines = []
        in_magic_multiline = False
        for l in lines:
            stripped = l.strip()
            if in_magic_multiline:
                py_lines.append("# " + l)
                if not stripped.endswith("\\"):
                    in_magic_multiline = False
            elif stripped.startswith("!") or stripped.startswith("%"):
                py_lines.append("# " + l)
                if stripped.endswith("\\"):
                    in_magic_multiline = True
            else:
                py_lines.append(l)
        py_src = "\n".join(py_lines)
        try:
            ast.parse(py_src)
            print(f"Cell {idx:02d} [CODE]: VALID ({len(lines)} lines)")
        except Exception as e:
            print(f"Cell {idx:02d} [CODE]: SYNTAX ERROR: {e}")
            print("--- Code ---")
            print(py_src)
            sys.exit(1)
    else:
        print(f"Cell {idx:02d} [{cell_type.upper()}]: OK ({len(src.splitlines())} lines)")

print("\nALL 31 CELLS VALIDATED SUCCESSFULLY!")
