import os, sys
import pandas as pd
from pathlib import Path

base_dir = Path("rag_module/ViFinQA/processed_data")

questions = [
    {"id": 2, "ticker": "ACB", "year": "2022", "term": "Thương mại"},
    {"id": 8, "ticker": "FTS", "year": "2021", "term": "lương"},
    {"id": 11, "ticker": "BID", "year": "2016", "term": "Tiền gửi tại các TCTD khác"},
    {"id": 16, "ticker": "CEO", "year": "2025", "term": "Vay và nợ thuê tài chính ngắn hạn"},
    {"id": 19, "ticker": "HHV", "year": "2023", "term": "quyền biểu quyết"},
    {"id": 20, "ticker": "GVR", "year": "2019", "term": "Visorutex"},
    {"id": 27, "ticker": "DLG", "year": "2024", "term": "Lưu chuyển tiền thuần"},
    {"id": 29, "ticker": "OGC", "year": "2019", "term": "người bán dài hạn"},
    {"id": 35, "ticker": "BVH", "year": "2015", "term": "Bảo Việt Nhân thọ"},
    {"id": 36, "ticker": "VRE", "year": "2016", "term": "Lợi thế thương mại"},
    {"id": 37, "ticker": "GEX", "year": "2018", "term": "cho thuê hoạt động"},
]

for q in questions:
    print("\n" + "="*80)
    print(f"Q{q['id']}: {q['ticker']} ({q['year']}) -> searching term '{q['term']}'")
    ticker_dir = base_dir / q["ticker"] / q["year"]
    if not ticker_dir.exists():
        print(f"Directory not found: {ticker_dir}")
        continue
    
    matches = []
    for csv_path in ticker_dir.rglob("*.csv"):
        try:
            df = pd.read_csv(csv_path)
            tb = df.get("Ten_Bang", pd.Series(["?"])).iloc[0] if "Ten_Bang" in df else "?"
            for c in df.columns:
                series = df[c].astype(str)
                m = series[series.str.contains(q["term"], case=False, na=False, regex=False)]
                if not m.empty:
                    for r_idx, val in m.items():
                        matches.append((csv_path.name, tb, c, val, r_idx, csv_path))
            if q["term"].lower() in str(tb).lower():
                matches.append((csv_path.name, tb, "Ten_Bang", tb, 0, csv_path))
        except Exception:
            pass
            
    print(f"Total matching files: {len(matches)}")
    seen = set()
    for fname, tb, col, val, r_idx, p in matches:
        if fname not in seen:
            seen.add(fname)
            print(f"  FILE: {fname}")
            print(f"    Table: {tb}")
            print(f"    Col '{col}' [row {r_idx}]: \"{val}\"")
