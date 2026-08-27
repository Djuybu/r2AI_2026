import os, sys
import pandas as pd
from pathlib import Path

base_dir = Path("rag_module/ViFinQA/processed_data")

cases = [
    {"q": "Q8 FTS 2021", "ticker": "FTS", "year": "2021", "terms": ["lương", "nhân viên", "chi phí quản lý", "chi phí hoạt động"]},
    {"q": "Q16 CEO 2025", "ticker": "CEO", "year": "2025", "terms": ["vay ngắn hạn", "vay và nợ", "ngắn hạn", "nợ phải trả"]},
    {"q": "Q19 HHV 2023", "ticker": "HHV", "year": "2023", "terms": ["biểu quyết", "quyền biểu quyết", "tỷ lệ", "công ty con", "liên kết"]},
    {"q": "Q20 GVR 2019", "ticker": "GVR", "year": "2019", "terms": ["Visorutex", "visorutex", "liên doanh", "liên kết"]},
    {"q": "Q27 DLG 2024", "ticker": "DLG", "year": "2024", "terms": ["Lưu chuyển tiền", "lưu chuyển tiền thuần", "hoạt động kinh doanh", "hoạt động đầu tư"]},
    {"q": "Q29 OGC 2019", "ticker": "OGC", "year": "2019", "terms": ["trả trước", "người bán dài hạn", "trả trước cho người bán"]},
    {"q": "Q36 VRE 2016", "ticker": "VRE", "year": "2016", "terms": ["lợi thế thương mại", "vô hình", "giá trị còn lại"]},
]

for c in cases:
    print("\n" + "="*80)
    print(f"CASE: {c['q']}")
    ticker_dir = base_dir / c["ticker"] / c["year"]
    if not ticker_dir.exists():
        print(f"Dir not found: {ticker_dir}")
        continue
    for p in ticker_dir.rglob("*.csv"):
        try:
            df = pd.read_csv(p)
            all_str = " ".join([str(x) for x in df.values.flatten() if pd.notna(x)])
            tb = df.get("Ten_Bang", pd.Series(["?"])).iloc[0] if "Ten_Bang" in df else "?"
            
            matched_terms = [t for t in c["terms"] if t.lower() in all_str.lower() or t.lower() in str(tb).lower()]
            if len(matched_terms) >= 2 or any(t.lower() in ["visorutex", "người bán dài hạn"] for t in matched_terms):
                print(f"  FOUND: {p.name}")
                print(f"    Table: {tb}")
                print(f"    Matched terms: {matched_terms}")
                # Print matching row
                for idx, row in df.iterrows():
                    r_str = " ".join([str(v) for v in row.values if pd.notna(v)])
                    for mt in matched_terms:
                        if mt.lower() in r_str.lower():
                            print(f"    Row {idx}: {row.dropna().to_dict()}")
                            break
        except Exception:
            pass
