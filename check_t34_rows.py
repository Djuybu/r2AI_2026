import os, sys, unicodedata, re
import pandas as pd
import numpy as np
from pathlib import Path
from rank_bm25 import BM25Okapi

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
import pickle
bm25_path = root_dir / "rag_module" / "bm25_index.pkl"
with open(bm25_path, "rb") as f:
    data = pickle.load(f)
    se._doc_mapping = data["doc_mapping"]
    se._company_map = se.load_company_map()

from verify_all_11_scoring import resolve_ticker, advanced_clean_query_content, compute_domain_boost, strip_accents

q = {"id": 2, "ticker": "ACB", "year": "2022", "user_query": "Số dư cho vay khách hàng ngành Thương mại của công ty mẹ Ngân hàng TMCP Á Châu (ACB) cuối năm 2022 là bao nhiêu triệu đồng?", "noi_dung": "Số dư cho vay khách hàng ngành Thương mại"}

ticker = resolve_ticker(q["ticker"])
content_clean = advanced_clean_query_content(q["noi_dung"], ticker, [q["year"]])
content_norm = strip_accents(content_clean)
raw_query = q["user_query"]
year = q["year"]

candidates = [d for d in se._doc_mapping if d.get("Ma_Doanh_Nghiep", "").strip() == ticker and str(d.get("Nam_Tai_Chinh", "")).strip() == str(year)]

row_items = []
for doc in candidates:
    raw_p = doc.get("csv_path", "")
    p_res = se._resolve_local_csv_path(raw_p)
    if p_res and p_res.exists():
        try:
            df = pd.read_csv(p_res)
            if not df.empty:
                col_name, col_series = se.get_first_meaningful_column(df)
                tb_name = ""
                if "Ten_Bang" in df.columns:
                    first_tb = df["Ten_Bang"].dropna()
                    if not first_tb.empty:
                        tb_name = str(first_tb.iloc[0]).strip()
                if not tb_name:
                    tb_name = doc.get("Ten_Bang", "")
                col_names = [str(c) for c in df.columns]
                all_text = " ".join(df.astype(str).values.flatten())[:1500]
                if col_series is not None:
                    for r_idx, val in col_series.dropna().items():
                        val_str = str(val).strip()
                        if len(val_str) >= 2:
                            comb = f"{tb_name} - {val_str}"
                            row_items.append({
                                "text": val_str,
                                "combined_text": comb,
                                "col_name": str(col_name),
                                "col_names": col_names,
                                "row_idx": r_idx,
                                "doc": doc,
                                "table_name": tb_name,
                                "csv_path": str(p_res),
                                "all_table_text": all_text,
                            })
        except Exception:
            pass

print(f"Total row items for ACB 2022: {len(row_items)}")
t34_rows = [r for r in row_items if "table_34" in r["csv_path"]]
print(f"Total rows from table_34: {len(t34_rows)}")
for r in t34_rows:
    boost = compute_domain_boost(content_clean, raw_query, r["table_name"], r["text"], r["col_names"], r["all_table_text"])
    print(f"   Row: '{r['text']}' | tb='{r['table_name']}' | file={Path(r['csv_path']).name} | Boost={boost}")
