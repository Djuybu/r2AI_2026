import os, sys, unicodedata, re
import pandas as pd
import numpy as np
from pathlib import Path
from rank_bm25 import BM25Okapi

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

from test_boost_unit import compute_domain_boost, strip_accents

content_clean = "cho vay khách hàng ngành Thương mại"
content_norm = strip_accents(content_clean)
raw_query = "Số dư cho vay khách hàng ngành Thương mại của công ty mẹ Ngân hàng TMCP Á Châu (ACB) cuối năm 2022 là bao nhiêu triệu đồng?"
ticker = "ACB"
year = "2022"

candidates = [d for d in se._doc_mapping if d.get("Ma_Doanh_Nghiep") == ticker and str(d.get("Nam_Tai_Chinh")) == str(year)]
print(f"Candidates count: {len(candidates)}")

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

print(f"Total row items collected: {len(row_items)}")

# Check items for table 34_0
t34_items = [item for item in row_items if "table_34_0" in item["csv_path"]]
print(f"Items in table 34_0: {len(t34_items)}")
for item in t34_items:
    b = compute_domain_boost(content_clean, raw_query, item["table_name"], item["text"], item["col_names"], item["all_table_text"])
    print(f"  Row '{item['text']}' | tb='{item['table_name']}' -> boost={b}")

# BM25 scores
corpus_tokens = [se.tokenize(item["combined_text"]) for item in row_items]
bm25_model = BM25Okapi(corpus_tokens)
query_tokens = se.tokenize(content_clean)
bm25_scores = bm25_model.get_scores(query_tokens)

pre_scores = []
for idx, item in enumerate(row_items):
    d_boost = compute_domain_boost(
        content_clean,
        raw_query,
        item["table_name"],
        item["text"],
        item["col_names"],
        item.get("all_table_text", "")
    )
    t_norm = strip_accents(item["text"])
    comb_norm = strip_accents(item["combined_text"])
    sub_boost = 0.0
    if content_norm in t_norm or (len(t_norm) >= 4 and t_norm in content_norm):
        sub_boost = 0.60
    elif content_norm in comb_norm:
        sub_boost = 0.40
    pre_scores.append(bm25_scores[idx] + (d_boost * 15.0) + (sub_boost * 15.0))

top_indices = np.argsort(pre_scores)[::-1][:150]
print(f"\nTop 5 pre-score ranked items:")
for rank, idx in enumerate(top_indices[:5], 1):
    item = row_items[idx]
    print(f"  #{rank} score={pre_scores[idx]:.2f} | {Path(item['csv_path']).name} | {item['table_name']} | '{item['text']}'")
