import os, sys
import pandas as pd
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

candidates = [d for d in se._doc_mapping if d.get("Ma_Doanh_Nghiep") == "ACB" and str(d.get("Nam_Tai_Chinh")) == "2022"]
print(f"Total candidates: {len(candidates)}")

errors = []
success = 0
for doc in candidates:
    raw_p = doc.get("csv_path", "")
    p_res = se._resolve_local_csv_path(raw_p)
    if not p_res:
        errors.append((raw_p, "Could not resolve path"))
        continue
    try:
        df = pd.read_csv(p_res)
        col_name, col_series = se.get_first_meaningful_column(df)
        success += 1
    except Exception as e:
        errors.append((str(p_res), str(e)))

print(f"Success: {success}, Errors: {len(errors)}")
if errors:
    print(f"First 10 errors:")
    for p, err in errors[:10]:
        print(f"  {Path(p).name}: {err}")
