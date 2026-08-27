import os, sys, re
import pandas as pd
from pathlib import Path

base_dir = Path("rag_module/ViFinQA/processed_data")

questions = [
    {"id": 2, "ticker": "ACB", "year": "2022", "query": "Số dư cho vay khách hàng ngành Thương mại", "keywords": ["Thương mại", "ngành", "cho vay"]},
    {"id": 8, "ticker": "FPT", "year": "2021", "query": "Chi phí lương và các khoản khác theo lương của công ty mẹ CTCP Chứng khoán FPT", "keywords": ["lương", "nhân viên", "Chứng khoán"]},
    {"id": 11, "ticker": "BID", "year": "2016", "query": "Số dư tiền gửi tại các TCTD khác", "keywords": ["tiền gửi tại", "tổ chức tín dụng", "tctd"]},
    {"id": 16, "ticker": "CEO", "year": "2025", "query": "Số dư vay ngắn hạn", "keywords": ["vay ngắn hạn", "vay và nợ"]},
    {"id": 19, "ticker": "HHV", "year": "2023", "query": "Tổng tỷ lệ quyền biểu quyết", "keywords": ["quyền biểu quyết", "tỷ lệ biểu quyết", "biểu quyết"]},
    {"id": 20, "ticker": "GVR", "year": "2019", "query": "Tỷ lệ biểu quyết của Xí nghiệp Liên doanh Visorutex", "keywords": ["Visorutex", "biểu quyết", "liên kết", "công ty con"]},
    {"id": 27, "ticker": "DLG", "year": "2024", "query": "Lưu chuyển tiền thuần từ hoạt động kinh doanh/đầu tư", "keywords": ["lưu chuyển", "hoạt động kinh doanh", "hoạt động đầu tư"]},
    {"id": 29, "ticker": "OGC", "year": "2019", "query": "Tổng số trả trước cho người bán dài hạn", "keywords": ["trả trước cho người bán", "người bán dài hạn", "dài hạn"]},
    {"id": 35, "ticker": "BVH", "year": "2015", "query": "Khoản phải thu từ Bảo Việt Nhân thọ", "keywords": ["Bảo Việt Nhân thọ", "phải thu", "liên quan"]},
    {"id": 36, "ticker": "VRE", "year": "2016", "query": "Giá trị còn lại của lợi thế thương mại (tổng cộng)", "keywords": ["lợi thế thương mại", "vô hình"]},
    {"id": 37, "ticker": "GEX", "year": "2018", "query": "Tổng cam kết cho thuê hoạt động", "keywords": ["thuê hoạt động", "cam kết", "thuê"]},
]

for q in questions:
    print("=" * 70)
    print(f"Q{q['id']}: {q['ticker']} ({q['year']}) - {q['query']}")
    print("=" * 70)
    ticker_dir = base_dir / q["ticker"] / q["year"]
    if not ticker_dir.exists():
        print(f"Directory not found: {ticker_dir}")
        continue
    
    csv_files = list(ticker_dir.rglob("*.csv"))
    print(f"Found {len(csv_files)} CSV files.")
    
    matches = []
    for csv_p in csv_files:
        try:
            df = pd.read_csv(csv_p)
            for c in df.columns:
                # search in series
                s = df[c].astype(str)
                for kw in q["keywords"]:
                    m = s[s.str.contains(kw, case=False, na=False, regex=False)]
                    if not m.empty:
                        for row_idx, val in m.items():
                            matches.append((csv_p.name, df.get("Ten_Bang", pd.Series(["?"])).iloc[0] if "Ten_Bang" in df else "?", c, val, row_idx, kw))
        except Exception as e:
            pass
    
    print(f"Matches found: {len(matches)}")
    # Print distinct files
    seen_files = set()
    for fname, ten_bang, col, val, row_idx, kw in matches:
        if (fname, kw) not in seen_files:
            seen_files.add((fname, kw))
            print(f"  File: {fname} | Table: {ten_bang} | Col: {col} | KW: '{kw}' | Row {row_idx}: \"{val}\"")
