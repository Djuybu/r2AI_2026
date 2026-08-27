import os, sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

def resolve_ticker(company_name: str) -> str:
    if not company_name:
        return ""
    c_upper = company_name.strip().upper()
    if se._company_map:
        tickers = {code.upper() for _, code in se._company_map}
        if c_upper in tickers:
            return c_upper
        for c_name, code in se._company_map:
            if c_name.lower() in company_name.lower() or company_name.lower() in c_name.lower():
                return code
        t_parsed, _, _ = se.parse_query(company_name, se._company_map)
        if t_parsed:
            return t_parsed
    return c_upper if len(c_upper) <= 5 else ""

tickers = ["ACB", "FTS", "BID", "CEO", "HHV", "GVR", "DLG", "OGC", "BVH", "VRE", "GEX"]
for t in tickers:
    resolved = resolve_ticker(t)
    cand = [d for d in se._doc_mapping if d.get("Ma_Doanh_Nghiep") == resolved]
    print(f"Ticker: {t} -> Resolved: '{resolved}' (Candidates in doc_mapping: {len(cand)})")
