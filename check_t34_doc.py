import os, sys
import pickle
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
bm25_path = root_dir / "rag_module" / "bm25_index.pkl"
with open(bm25_path, "rb") as f:
    data = pickle.load(f)
    se._doc_mapping = data["doc_mapping"]

cands = [d for d in se._doc_mapping if d.get("Ma_Doanh_Nghiep") == "ACB" and str(d.get("Nam_Tai_Chinh")) == "2022"]
t34_cands = [d for d in cands if "34" in str(d.get("csv_path"))]

print(f"Total ACB 2022 docs: {len(cands)}")
print(f"Docs mentioning 34: {len(t34_cands)}")
for d in t34_cands:
    raw_p = d.get("csv_path", "")
    p_res = se._resolve_local_csv_path(raw_p)
    print(f"raw_p='{raw_p}' -> p_res='{p_res}' exists={p_res.exists() if p_res else False}")
    if p_res and p_res.exists():
        import pandas as pd
        df = pd.read_csv(p_res)
        col_name, col_series = se.get_first_meaningful_column(df)
        print(f"   col_name={col_name}, col_series_len={len(col_series) if col_series is not None else 0}")
