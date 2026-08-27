import os, sys
import pandas as pd
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

p1 = Path(r"d:\hobby_project\cocopila\r2AI_2026\rag_module\ViFinQA\processed_data\ACB\2022\ACB_financial_statements_2022_separate\ACB_financial_statements_2022_separate_table_34.csv")
df1 = pd.read_csv(p1)
col_name, col_series = se.get_first_meaningful_column(df1)
print(f"table_34.csv: col_name={col_name}, len={len(col_series) if col_series is not None else 0}")
if col_series is not None:
    print(col_series.head(5))

p2 = Path(r"d:\hobby_project\cocopila\r2AI_2026\rag_module\ViFinQA\processed_data\FTS\2021\FTS_financial_statements_2021_table_44_0.csv")
if not p2.exists():
    p2 = list(Path(r"d:\hobby_project\cocopila\r2AI_2026\rag_module\ViFinQA\processed_data\FTS\2021").glob("*table_44*"))[0]
df2 = pd.read_csv(p2)
col_name2, col_series2 = se.get_first_meaningful_column(df2)
print(f"\n{p2.name}: col_name={col_name2}, len={len(col_series2) if col_series2 is not None else 0}")
if col_series2 is not None:
    print(col_series2.head(5))
