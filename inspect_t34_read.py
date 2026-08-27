import os, sys
import pandas as pd
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se

p = Path("rag_module/ViFinQA/processed_data/ACB/2022/ACB_financial_statements_2022_separate/ACB_financial_statements_2022_separate_table_34_0.csv")
print(f"Path exists: {p.exists()}")
df = pd.read_csv(p)
print(f"Columns: {list(df.columns)}")
col_name, col_series = se.get_first_meaningful_column(df)
print(f"First meaningful column name: '{col_name}'")
print(f"Meaningful col series:\n{col_series}")

for r_idx, val in col_series.dropna().items():
    val_str = str(val).strip()
    print(f"  row {r_idx}: '{val_str}' (len={len(val_str)})")
