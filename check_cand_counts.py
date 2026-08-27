import os, sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

for ticker, year in [("ACB", "2022"), ("FTS", "2021"), ("BID", "2016"), ("CEO", "2025"), ("HHV", "2023"), ("GVR", "2019"), ("DLG", "2024"), ("OGC", "2019"), ("BVH", "2015"), ("VRE", "2016"), ("GEX", "2018")]:
    cands = [d for d in se._doc_mapping if d.get("Ma_Doanh_Nghiep") == ticker and str(d.get("Nam_Tai_Chinh")) == year]
    print(f"Ticker={ticker}, Year={year} -> Count={len(cands)}")
