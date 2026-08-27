import os, sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

from verify_all_11_scoring import full_upgraded_search, compute_domain_boost

q = {"id": 2, "ticker": "ACB", "year": "2022", "user_query": "Số dư cho vay khách hàng ngành Thương mại của công ty mẹ Ngân hàng TMCP Á Châu (ACB) cuối năm 2022 là bao nhiêu triệu đồng?", "noi_dung": "Số dư cho vay khách hàng ngành Thương mại"}

res = full_upgraded_search(
    company_name=q["ticker"],
    content=q["noi_dung"],
    raw_query=q["user_query"],
    year=q["year"],
    report_type=None,
    top_k=10
)

print(f"Top {len(res)} results for Q2:")
for idx, r in enumerate(res, 1):
    print(f"#{idx} RRF={r.get('rrf_score')} | {Path(r.get('csv_path')).name} | {r.get('Ten_Bang')} | Sample: '{r.get('matched_sample')}'")
