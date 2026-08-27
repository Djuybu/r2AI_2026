import os, sys, unicodedata, re
import pandas as pd
import numpy as np
from pathlib import Path
from rank_bm25 import BM25Okapi

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
# Load only bm25 and mappings, don't load embed_model/qdrant!
import pickle
bm25_path = root_dir / "rag_module" / "bm25_index.pkl"
with open(bm25_path, "rb") as f:
    data = pickle.load(f)
    se._doc_mapping = data["doc_mapping"]
    se._company_map = se.load_company_map()

from verify_all_11_scoring import resolve_ticker, advanced_clean_query_content, compute_domain_boost, strip_accents

questions = [
    {"id": 2, "ticker": "ACB", "year": "2022", "user_query": "Số dư cho vay khách hàng ngành Thương mại của công ty mẹ Ngân hàng TMCP Á Châu (ACB) cuối năm 2022 là bao nhiêu triệu đồng?", "noi_dung": "Số dư cho vay khách hàng ngành Thương mại"},
    {"id": 8, "ticker": "FTS", "year": "2021", "user_query": "Chi phí lương và các khoản khác theo lương của công ty mẹ CTCP Chứng khoán FPT trong năm 2021 là bao nhiêu tỷ đồng?", "noi_dung": "Chi phí lương và các khoản khác theo lương"},
    {"id": 11, "ticker": "BID", "year": "2016", "user_query": "Số dư tiền gửi tại các TCTD khác cuối năm 2016 của Ngân hàng TMCP Đầu tư và Phát triển Việt Nam (BID) là bao nhiêu triệu đồng?", "noi_dung": "Số dư tiền gửi tại các TCTD khác"},
    {"id": 16, "ticker": "CEO", "year": "2025", "user_query": "Số dư vay ngắn hạn của công ty mẹ CEO cuối năm 2025 là bao nhiêu tỷ đồng?", "noi_dung": "Số dư vay ngắn hạn"},
    {"id": 19, "ticker": "HHV", "year": "2023", "user_query": "Tổng tỷ lệ quyền biểu quyết của công ty mẹ CTCP Đầu tư Hạ tầng Giao thông Đèo Cả năm 2023 là bao nhiêu phần trăm?", "noi_dung": "Tổng tỷ lệ quyền biểu quyết"},
    {"id": 20, "ticker": "GVR", "year": "2019", "user_query": "Tỷ lệ biểu quyết của Xí nghiệp Liên doanh Visorutex của công ty mẹ GVR đến ngày 31/12/2019 là bao nhiêu %?", "noi_dung": "Tỷ lệ biểu quyết của Xí nghiệp Liên doanh Visorutex"},
    {"id": 27, "ticker": "DLG", "year": "2024", "user_query": "Lưu chuyển tiền thuần từ hoạt động kinh doanh của công ty mẹ CTCP Tập đoàn Đức Long Gia Lai (DLG) năm 2024 là bao nhiêu triệu đồng?", "noi_dung": "Lưu chuyển tiền thuần từ hoạt động kinh doanh"},
    {"id": 29, "ticker": "OGC", "year": "2019", "user_query": "Tổng số trả trước cho người bán dài hạn của OGC đến ngày 31 tháng 12 năm 2019 là bao nhiêu triệu đồng?", "noi_dung": "Tổng số trả trước cho người bán dài hạn"},
    {"id": 35, "ticker": "BVH", "year": "2015", "user_query": "Khoản phải thu từ Bảo Việt Nhân thọ của công ty mẹ Tập đoàn Bảo Việt (BVH) cuối năm 2015 là bao nhiêu triệu đồng?", "noi_dung": "Khoản phải thu từ Bảo Việt Nhân thọ"},
    {"id": 36, "ticker": "VRE", "year": "2016", "user_query": "Giá trị còn lại của lợi thế thương mại (tổng cộng) của CTCP Vincom Retail (VRE) là bao nhiêu triệu đồng đến ngày 31/12/2016?", "noi_dung": "Giá trị còn lại của lợi thế thương mại (tổng cộng)"},
    {"id": 37, "ticker": "GEX", "year": "2018", "user_query": "Tổng cam kết cho thuê hoạt động của công ty mẹ CTCP Tập đoàn GELEX (GEX) đến ngày 31/12/2018 là bao nhiêu tỷ đồng?", "noi_dung": "Tổng cam kết cho thuê hoạt động"},
]

for q in questions:
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
                
    if not row_items:
        print(f"Q{q['id']}: NO ROW ITEMS FOUND!")
        continue
        
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
        
    top_indices = np.argsort(pre_scores)[::-1][:5]
    print(f"=======================================================")
    print(f"Q{q['id']}: {ticker} ({year}) | query='{content_clean}'")
    for idx in top_indices:
        item = row_items[idx]
        print(f"   Score={pre_scores[idx]:.2f} (bm25={bm25_scores[idx]:.2f}) | {Path(item['csv_path']).name} | {item['table_name'][:35]} | \"{item['text']}\"")
