import json
import ast
import sys

nb_path = "notebooks/kaggle_bootstrap.ipynb"
with open(nb_path, "r", encoding="utf-8") as f:
    nb = json.load(f)

print(f"Total cells: {len(nb['cells'])}")

target_cells = [11, 15, 19, 23]
for idx in target_cells:
    if idx < len(nb['cells']):
        c = nb['cells'][idx]
        src = "".join(c.get("source", ""))
        print(f"--- Cell {idx} (type={c['cell_type']}) ---")
        print(f"Length: {len(src)} characters, {len(src.splitlines())} lines")
        if c['cell_type'] == 'code':
            try:
                ast.parse(src)
                print("AST parsing: SUCCESS (valid Python)")
            except Exception as e:
                print(f"AST parsing: FAILED ({e})")
                sys.exit(1)
        for line in src.splitlines()[:5]:
            print(f"  {line}")
    else:
        print(f"Cell {idx} DOES NOT EXIST")
        sys.exit(1)

print("ALL TARGET CELLS VALID")
