"""Test what tickers match common Vietnamese ASCII words in code_stock.csv."""
import sys
from pathlib import Path
repo_root = Path("d:/hobby_project/cocopila/r2AI_2026")
sys.path.insert(0, str(repo_root))

from pipeline.src.nodes.query_parser import _get_stock_mappings, _normalize_company_name

name_to_code, all_tickers = _get_stock_mappings()
print(f"Total tickers in code_stock.csv: {len(all_tickers)}")
print(f"Total name mappings: {len(name_to_code)}")

vietnamese_ascii_words = [
    "doanh", "thu", "thuan", "lai", "lo", "chi", "phi", "gia", "tri", "von",
    "chu", "so", "huu", "tai", "san", "hang", "ton", "kho", "tien", "gui",
    "ngan", "hang", "nam", "quy", "tong", "thue", "tra", "phai", "vay"
]

matching_tickers = []
for w in vietnamese_ascii_words:
    if w.upper() in all_tickers:
        matching_tickers.append((w, w.upper()))

print(f"Vietnamese ASCII words matching tickers: {matching_tickers}")

for w, t in matching_tickers:
    query = f"Doanh thu {w} năm 2021 là bao nhiêu?"
    resolved = _normalize_company_name("", query)
    print(f"Query: {query!r} -> Resolved ticker: {resolved!r}")
