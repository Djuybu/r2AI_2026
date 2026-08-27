import os, sys, unicodedata, re
import pandas as pd
import numpy as np
from pathlib import Path
from rank_bm25 import BM25Okapi

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

from verify_all_11_scoring import resolve_ticker, advanced_clean_query_content, compute_domain_boost, strip_accents

def debug_search(company_name, content, raw_query, year):
    ticker = resolve_ticker(company_name)
    content_clean = advanced_clean_query_content(content, ticker, [year] if year else None)
    content_norm = strip_accents(content_clean)
    
    candidates = [d for d in se._doc_mapping if d.get("Ma_Doanh_Nghiep", "").strip() == ticker and str(d.get("Nam_Tai_Chinh", "")).strip() == str(year)]
    print(f"DEBUG [{ticker} {year}]: candidates={len(candidates)}, content_clean='{content_clean}'")
    
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
            except Exception as e:
                pass
                
    print(f"DEBUG [{ticker} {year}]: row_items={len(row_items)}")
    
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
        
    top_indices = np.argsort(pre_scores)[::-1][:10]
    print(f"DEBUG [{ticker} {year}] TOP 5 PRE-SCORES:")
    for idx in top_indices[:5]:
        item = row_items[idx]
        print(f"   pre_score={pre_scores[idx]:.2f} (bm25={bm25_scores[idx]:.2f}) | {Path(item['csv_path']).name} | {item['table_name']} | {item['text']}")

debug_search("ACB", "Số dư cho vay khách hàng ngành Thương mại", "Số dư cho vay khách hàng ngành Thương mại của công ty mẹ Ngân hàng TMCP Á Châu (ACB) cuối năm 2022 là bao nhiêu triệu đồng?", "2022")
debug_search("FTS", "Chi phí lương và các khoản khác theo lương", "Chi phí lương và các khoản khác theo lương của công ty mẹ CTCP Chứng khoán FPT trong năm 2021 là bao nhiêu tỷ đồng?", "2021")
